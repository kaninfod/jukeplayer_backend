"""Plain data models for the smart-random picker."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Album:
    """One owned album, as served by the music source."""

    album_id: str
    artist: str
    name: str
    year: str = ""
    genres: tuple[str, ...] = ()
    play_count: Optional[int] = None

    @property
    def key(self) -> tuple[str, str]:
        from .text import album_key

        return album_key(self.artist, self.name)


@dataclass
class ListeningProfile:
    """The in-memory ListenBrainz view used by the picker.

    ``quarter_keys`` are release groups played in the last three months,
    ``all_time_keys`` everything ever scrobbled, ``top_album_keys`` the 20
    most-played this quarter. The weights are normalised to their maximum
    (best artist/genre = 1.0).
    """

    quarter_keys: set[tuple[str, str]] = field(default_factory=set)
    all_time_keys: set[tuple[str, str]] = field(default_factory=set)
    top_album_keys: set[tuple[str, str]] = field(default_factory=set)
    artist_weights: dict[str, float] = field(default_factory=dict)
    genre_weights: dict[str, float] = field(default_factory=dict)
    recent_keys: set[tuple[str, str]] = field(default_factory=set)
    fetched_at: float = 0.0


@dataclass
class AlbumPick:
    """The chosen album plus a human-readable reason for the log/display."""

    album_id: str
    artist: str
    album: str
    year: str
    reason: str
    score: float
    components: dict[str, float] = field(default_factory=dict)
