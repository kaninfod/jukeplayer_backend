"""The small data objects Subsonic returns to the playback layer.

These are deliberately plain dataclasses: they keep gonic's raw JSON shape
out of PlaybackService, but there is no source abstraction behind them.
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SubsonicTrack:
    track_id: str            # namespaced for now: "subsonic:tr-8880"
    title: str
    artist: str
    duration: str            # seconds as str — PlaylistItem.duration keeps this shape
    track_number: int = 0


@dataclass
class SubsonicAlbum:
    album_id: str            # namespaced for now: "subsonic:al-678"
    title: str
    artist: str
    year: str = ""
    cover_url: Optional[str] = None
    starred: bool = False
    tracks: List[SubsonicTrack] = field(default_factory=list)
