"""YTMusicSource — the second citizen behind the seam (backend-first slice).

- id/name/capabilities: SEARCH + COVER_ART; no BROWSE (the kiosk library's
  yt presence comes via the collection ledger) and no SCROBBLE.
- `load_album` accepts both id shapes: MPREb… (store browse id → get_album)
  and OLAK5uy… (share-link playlist id → get_playlist; its title = the album).
- `stream_url` returns the plain watch URL; the per-speaker mpv resolves it
  via yt-dlp (ytdl on). Resolved fresh at play time — the URLs expire.
- `cover_art` fetches the thumb bytes for the CoverService cache (the kiosk
  CSP only shows same-origin images).
- credentials/token live in the config store's `sources.ytmusic` section.
"""
import logging
import re
from dataclasses import dataclass
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


class YTMusicSource(SourceProvider):
    id = "ytmusic"
    name = "YouTube Music"
    capabilities = frozenset({SourceCapability.SEARCH, SourceCapability.COVER_ART})

    def __init__(self, config: dict):
        """config = the store's sources.ytmusic dict (client creds + token)."""
        if not config.get("token"):
            raise ValueError("ytmusic has no OAuth token yet — run the auth flow first")
        self.config = config
        self._client = None

    def _ytm(self):
        """The ytmusicapi client, built lazily and rebuilt if the token
        changed underneath (a re-auth swaps the stored token)."""
        desired = self.config.get("token")
        if self._client is None:
            from ytmusicapi import YTMusic, OAuthCredentials
            creds = OAuthCredentials(client_id=self.config["client_id"],
                                     client_secret=self.config["client_secret"])
            self._client = YTMusic(auth=desired, oauth_credentials=creds)
            self._client_token = desired
        return self._client

    def is_ready(self) -> bool:
        """One cheap authed call proves the token still works."""
        if not self.config.get("token"):
            return False
        try:
            self._ytm().get_library_songs(limit=1)
            return True
        except Exception as e:
            logger.info(f"ytmusic is_ready probe failed: {e}")
            return False

    def load_album(self, album_id: str) -> SourceAlbum:
        aid = album_id.strip()
        if aid.startswith("MPREb"):
            return self._load_browse_album(aid)
        if aid.startswith("OLAK5uy"):
            return self._load_playlist_album(aid)
        raise ValueError(
            f"Unsupported ytmusic album id '{aid}' — use an MPREb… (album) "
            f"or an OLAK5uy… (playlist/album-share) id")

    def _load_browse_album(self, aid: str) -> SourceAlbum:
        al = self._ytm().get_album(aid)
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
            cover_url=_largest_thumb(al.get("thumbnails") or [{}])["url"]
                if al.get("thumbnails") else None,
            tracks=tracks,
        )

    def _load_playlist_album(self, pid: str) -> SourceAlbum:
        pl = self._ytm().get_playlist(pid)
        if not pl:
            raise ValueError(f"Playlist not found on YouTube Music: {pid}")
        tracks = []
        for i, t in enumerate(pl.get("tracks") or [], start=1):
            if not t.get("videoId"):
                continue
            tracks.append(SourceTrack(
                track_id=qualify(self.id, t["videoId"]),
                title=t.get("title") or "",
                artist=_artist_name((t.get("artists") or [{}])[0])
                       or self.get_playlist_artist(pl),
                duration=duration_to_seconds(t.get("duration_seconds") or t.get("duration")),
                track_number=t.get("index") or i,
            ))
        if not tracks:
            raise ValueError(f"No videoIds resolved for YouTube Music playlist {pid}")
        return SourceAlbum(
            album_id=qualify(self.id, pid),
            title=pl.get("title") or "",
            artist=self.get_playlist_artist(pl),
            year=str(pl.get("year") or ""),
            cover_url=_largest_thumb(pl.get("thumbnails") or [{}])["url"]
                if pl.get("thumbnails") else None,
            tracks=tracks,
        )

    def get_playlist_artist(self, pl: dict) -> str:
        """A playlist's 'artist': the author when it's an album-style playlist."""
        owner = pl.get("owner")
        if isinstance(owner, dict) and owner.get("name"):
            return owner["name"]
        if isinstance(owner, list):
            names = [o.get("name", "") for o in owner if isinstance(o, dict)]
            return names[0] if names else ""
        ch = pl.get("channel")
        if isinstance(ch, dict):
            return ch.get("name", "")
        return owner or ""

    def stream_url(self, track_id: str) -> StreamSpec:
        _, raw = unqualify(track_id)
        return StreamSpec(url=f"https://www.youtube.com/watch?v={raw}",
                          content_type="application/x-youtube", external=True)

    def cover_art(self, album_id: str) -> bytes:
        """Fetch the album/playlist's thumbnail bytes for the CoverService
        cache. Raises when the thumb can't be fetched (the caller owns the
        fallback)."""
        import requests as requests_mod
        aid = unqualify(album_id)[1]
        if aid.startswith("MPREb"):
            url = _largest_thumb(self._ytm().get_album(aid).get("thumbnails") or [{}])["url"]
        elif aid.startswith("OLAK5uy"):
            url = _largest_thumb(self._ytm().get_playlist(aid).get("thumbnails") or [{}])["url"]
        else:
            raise ValueError(f"Unsupported ytmusic album id for cover art: {album_id}")
        if not url:
            raise ValueError(f"No thumbnail found for {album_id}")
        resp = requests_mod.get(url, timeout=15)
        resp.raise_for_status()
        return resp.content

    def search(self, query: str, limit: int = 20) -> list:
        """The crate: tracks + albums as SourceHits."""
        results = self._ytm().search(query, filter=None) or []
        hits = []
        for r in results[:limit]:
            kind = r.get("resultType", "")
            if kind in ("video", "song"):
                hits.append(dict(kind="track", track_id=qualify(self.id, r["videoId"]),
                                 title=r.get("title", ""), artist=_artist_name((r.get("artists") or [{}])[0])))
            elif kind in ("album", "playlist"):
                hits.append(dict(kind="album", album_id=qualify(self.id, r.get("albumId") or r.get("playlistId") or ""),
                                 title=r.get("title", ""), artist=_artist_name((r.get("artists") or [{}])[0])))
        return hits

    def scrobble(self, track_id: str) -> bool:
        return False  # SCROBBLE not a ytmusic capability for now


def _largest_thumb(thumbs: list) -> dict:
    """The BIGGEST thumbnail (ytmusicapi rows: {width,height,url})."""
    return max((t for t in thumbs if isinstance(t, dict) and t.get("url")),
               key=lambda t: t.get("width") or 0, default={})