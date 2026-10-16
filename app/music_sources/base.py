"""The music-source seam (the two-phase design agreed 2026-10-10 session):
the juke core consumes ALBUMS and PLAYABLE STREAMS through one thin
interface; each source (gonic today, online sources later) sits behind it.

Shape notes (the Music-Assistant steal — concept only, no code):
- the manifest pattern is reduced to a class attr + the capability flags;
- the two-phase audio flow collapses to ONE seam: stream_url() returns what
  the per-speaker mpv plays (a plain http stream for gonic, a
  yt-dlp-routed url for online sources) — mpv IS the audio pipeline.
- deliberate-action principle: the juke plays ALBUMS a human chose; there
  is no suggestion machinery on this seam (queue ends = silence).

id discipline: everything crossing the seam is NAMESPACED ("subsonic:al-678"
/ "subsonic:tr-8880") — cards, queue item ids, the future album store.
Bare (unqualified) ids stay valid anywhere as "the default source" (all
RFID cards encoded before this seam are bare — they keep working).
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class SourceCapability(str, Enum):
    BROWSE = "browse"        # the kiosk-library browsing faculty (only subsonic/gonic today)
    SEARCH = "search"        # the search-panel/crate surface
    SCROBBLE = "scrobble"    # now-playing notifications upstream
    COVER_ART = "cover_art"  # raw cover bytes for the CoverService cache


@dataclass
class StreamSpec:
    """What the per-speaker mpv plays for one track."""
    url: str
    content_type: Optional[str] = None
    external: bool = False   # True = an online-source url (yt-dlp class)


@dataclass
class SourceTrack:
    track_id: str            # NAMESPACED ("subsonic:tr-8880")
    title: str
    artist: str
    duration: str            # seconds as str — PlaylistItem.duration keeps its str shape
    track_number: int = 0


@dataclass
class SourceAlbum:
    album_id: str            # NAMESPACED ("subsonic:al-678")
    title: str
    artist: str
    year: str = ""
    cover_url: Optional[str] = None   # the source's own preferred rendering (proxy url / thumb)
    tracks: List[SourceTrack] = field(default_factory=list)


@dataclass
class SourceHit:
    """A search-crate row: a track or an album hit, still source-resident."""
    kind: str                # "track" | "album"
    track_id: Optional[str] = None
    album_id: Optional[str] = None
    title: str = ""
    artist: str = ""
    year: str = ""
    cover_url: Optional[str] = None


def qualify(provider_id: str, raw_id: str) -> str:
    """subsonic + al-678 → 'subsonic:al-678' (idempotent)."""
    prefix = f"{provider_id}:"
    if str(raw_id).startswith(prefix):
        return raw_id
    return prefix + str(raw_id)


def unqualify(qualified_id: str) -> tuple:
    """'subsonic:al-678' → ('subsonic', 'al-678'). Bare ids → (None, id) —
    the caller falls back to the default source (the legacy-card path)."""
    sep = str(qualified_id or "").find(":")
    if sep <= 0:
        return None, qualified_id
    return qualified_id[:sep], qualified_id[sep + 1:]


class SourceProvider:
    """The seam between the juke core and a music source. One source per
    instance; every id crossing the seam is namespaced via qualify/unqualify."""
    id: str = None
    name: str = None
    capabilities: frozenset = frozenset()

    def is_ready(self) -> bool:
        """Cheap liveness/auth probe for the not-ready messaging."""
        raise NotImplementedError

    def load_album(self, album_id: str) -> SourceAlbum:
        """Resolve an album (SOURCE-RAW id) with its ordered track list.
        Raises ValueError when the album is unknown/empty."""
        raise NotImplementedError

    def stream_url(self, track_id: str) -> StreamSpec:
        """The playable url for a track (NAMESPACED id). No I/O: building the
        url must stay cheap — resolution of online streams belongs to the
        player-side extractor (yt-dlp), not to this seam."""
        raise NotImplementedError

    def cover_art(self, album_id: str) -> bytes:
        """RAW image bytes for the CoverService cache."""
        raise NotImplementedError

    def scrobble(self, track_id: str) -> bool:
        """Now-playing notification (only when SCROBBLE in capabilities)."""
        raise NotImplementedError