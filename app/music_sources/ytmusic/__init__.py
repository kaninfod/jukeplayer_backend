"""YTMusicSource — the second citizen behind the seam (backend-first slice).

AUTH MODE (2026-10-16): PUBLIC/un-authed ONLY — google's private endpoints
reject the device-flow OAuth tokens (FAILED_PRECONDITION, proven live with
a correct TV-client token and a primary account; MA's production provider
went through the same wall and settled on cookies+PO-token). Any stored
token stays parked in the config, inert; the parked auth code (auth.py + the
/api/sources/ytmusic/auth* routes) awaits the day the wall moves.

- `load_album` accepts both id shapes: MPREb… (→ get_album) and
  OLAK5uy… (→ get_playlist; its title = the album's name).
- `stream_url` returns the plain watch URL; the per-speaker mpv resolves it
  via yt-dlp (ytdl on). Resolved fresh at play time — the URLs expire.
- `cover_art` fetches the thumb bytes for the CoverService cache (the kiosk
  CSP shows same-origin images only).
"""
import logging
import re
from typing import Optional

from app.music_sources.base import (
    SourceCapability, SourceProvider, SourceAlbum, SourceTrack,
    StreamSpec, qualify, unqualify,
)

logger = logging.getLogger(__name__)

_YTM_DURATION_RE = re.compile(r"^(?:(\d+):)?(\d+):(\d+)$")


def duration_to_seconds(value) -> str:
    """ytmusicapi mixes formats: album tracks = duration_seconds (int),
    playlist items sometimes = 'M:SS' strings. The queue wants seconds-str."""
    if value is None:
        return "0"
    if isinstance(value, (int, float)):
        return str(int(value))
    m = _YTM_DURATION_RE.match(str(value).strip())
    if not m:
        return "0"
    h, mnt, sec = m.groups()
    total = int(sec or 0) + int(mnt or 0) * 60 + int(h or 0) * 3600
    return str(total)


def _artist_name(entry) -> str:
    """ytmusicapi artist fields: {'name': …} dicts or plain strings."""
    if isinstance(entry, dict):
        return entry.get("name", "")
    return entry or ""


def _largest_thumb(thumbs: list) -> dict:
    """The BIGGEST thumbnail (rows: {width,height,url})."""
    return max((t for t in thumbs if isinstance(t, dict) and t.get("url")),
               key=lambda t: t.get("width") or 0, default={})


class YTMusicSource(SourceProvider):
    id = "ytmusic"
    name = "YouTube Music"
    capabilities = frozenset({SourceCapability.SEARCH, SourceCapability.COVER_ART})

    def __init__(self, config: Optional[dict] = None):
        self.config = dict(config or {})
        # THE PUBLIC MODE IS THE ONLY ACTIVE MODE (2026-10-16): google's
        # private endpoints reject the device-flow OAuth tokens outright
        # (FAILED_PRECONDITION — proven live, and MA's production provider
        # carries the same history). Any stored token stays parked in the
        # config, inert, until that wall moves.
        self._token = None
        self._client = None

    def _ytm(self):
        if self._client is None:
            from ytmusicapi import YTMusic
            self._client = YTMusic()   # the public surface: search + albums + playlists
            logger.info("[ytm] public (un-authed) client built")
        return self._client

    def is_ready(self) -> bool:
        """The public surface = effectively always ready."""
        return True

    def load_album(self, album_id: str) -> SourceAlbum:
        aid = str(album_id or "").strip()
        if aid.startswith("MPREb"):
            return self._load_browse_album(aid)
        if aid.startswith("OLAK5uy"):
            return self._load_playlist_album(aid)
        raise ValueError(
            f"Unsupported ytmusic album id '{aid}' — use an MPREb… (album) "
            f"or an OLAK5uy… (playlist/album-share) id")

    def _load_browse_album(self, aid: str) -> SourceAlbum:
        al = self._ytm().get_album(aid) or {}
        if not al:
            raise ValueError(f"Album not found on YouTube Music: {aid}")
        artist = _artist_name((al.get("artists") or [{}])[0])
        tracks = [
            SourceTrack(
                track_id=qualify(self.id, t.get("videoId") or ""),
                title=t.get("title") or "",
                artist=_artist_name((t.get("artists") or [{}])[0]) or artist,
                duration=duration_to_seconds(t.get("duration_seconds") or t.get("duration")),
                track_number=t.get("albumTrackIndex") or t.get("trackNumber") or 0,
            )
            for t in (al.get("tracks") or []) if t.get("videoId")
        ]
        if not tracks:
            raise ValueError(f"No videoIds resolved for YouTube Music album {aid}")
        return SourceAlbum(
            album_id=qualify(self.id, aid),
            title=al.get("title") or "",
            artist=artist,
            year=str(al.get("year") or ""),
            cover_url=_largest_thumb(al.get("thumbnails") or []).get("url"),
            tracks=tracks,
        )

    def _load_playlist_album(self, pid: str) -> SourceAlbum:
        pl = self._ytm().get_playlist(pid) or {}
        if not pl:
            raise ValueError(f"Playlist not found on YouTube Music: {pid}")
        artist = self._playlist_artist(pl)
        tracks = []
        for i, t in enumerate(pl.get("tracks") or [], start=1):
            if not t.get("videoId"):
                continue
            tracks.append(SourceTrack(
                track_id=qualify(self.id, t["videoId"]),
                title=t.get("title") or "",
                artist=_artist_name((t.get("artists") or [{}])[0]) or artist,
                duration=duration_to_seconds(t.get("duration_seconds") or t.get("duration")),
                track_number=t.get("index") or i,
            ))
        if not tracks:
            raise ValueError(f"No videoIds resolved for YouTube Music playlist {pid}")
        return SourceAlbum(
            album_id=qualify(self.id, pid),
            title=pl.get("title") or "",
            artist=artist,
            year=str(pl.get("year") or ""),
            cover_url=_largest_thumb(pl.get("thumbnails") or []).get("url"),
            tracks=tracks,
        )

    def _playlist_artist(self, pl: dict) -> str:
        """A playlist's 'artist': the owner/channel (an album-style playlist's
        author), else empty (the per-track artists carry the names)."""
        owner = pl.get("owner")
        if isinstance(owner, dict) and owner.get("name"):
            return owner["name"]
        if isinstance(owner, list):
            names = [o.get("name", "") for o in owner if isinstance(o, dict)]
            if names:
                return names[0]
        ch = pl.get("channel")
        if isinstance(ch, dict):
            return ch.get("name", "")
        if isinstance(owner, str) and owner:
            return owner
        return ""

    def stream_url(self, track_id: str) -> StreamSpec:
        _, raw = unqualify(track_id)
        return StreamSpec(url=f"https://www.youtube.com/watch?v={raw}",
                          content_type="application/x-youtube", external=True)

    def cover_art(self, album_id: str) -> bytes:
        """Fetch the album/playlist's thumbnail bytes for the CoverService
        cache."""
        import requests as requests_mod
        aid = unqualify(album_id)[1]
        if aid.startswith("MPREb"):
            url = _largest_thumb(self._ytm().get_album(aid).get("thumbnails") or []).get("url")
        elif aid.startswith("OLAK5uy"):
            url = _largest_thumb(self._ytm().get_playlist(aid).get("thumbnails") or []).get("url")
        else:
            raise ValueError(f"Unsupported ytmusic album id for cover art: {album_id}")
        if not url:
            raise ValueError(f"No thumbnail found for {album_id}")
        resp = requests_mod.get(url, timeout=15)
        resp.raise_for_status()
        return resp.content

    def search(self, query: str, limit: int = 20) -> list:
        """The crate (the public search): tracks + albums as SourceHit-shaped
        dicts. Un-authed album rows carry browseId AND playlistId."""
        results = self._ytm().search(query) or []
        hits = []
        for r in results[:limit]:
            kind = r.get("resultType", "")
            if kind in ("video", "song") and r.get("videoId"):
                hits.append(dict(kind="track", track_id=qualify(self.id, r["videoId"]),
                                 title=r.get("title", ""),
                                 artist=_artist_name((r.get("artists") or [{}])[0]),
                                 duration=duration_to_seconds(r.get("duration"))))
            elif kind in ("album", "playlist") and (r.get("browseId") or r.get("playlistId")):
                hits.append(dict(
                    kind="album",
                    album_id=qualify(self.id, r.get("browseId") or r.get("playlistId")),
                    title=r.get("title", ""),
                    artist=_artist_name((r.get("artists") or [{}])[0]),
                    playlist_id=r.get("playlistId", "")))
        return hits

    def scrobble(self, track_id: str) -> bool:
        return False  # SCROBBLE is not a ytmusic capability for now