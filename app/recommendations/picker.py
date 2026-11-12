"""Pure scoring and sampling for the smart-random picker.

The behaviour is intentionally explainable:

- **not thought about** — top-20 and last-quarter albums are excluded; the
  remaining albums score highest when they were never played or were not
  played in the last three months;
- **probably liked** — artist affinity (this quarter's top artists) and genre
  affinity (the current hour's genres) raise the score;
- **oddball** — with a 15% chance the pick is restricted to albums with no
  affinity at all.
"""

from __future__ import annotations

import random
from typing import Iterable, Optional

from .models import Album, AlbumPick, ListeningProfile
from .text import fold

ODDBALL_RATE = 0.15
SHORTLIST = 20


def score_album(
    album: Album,
    profile: ListeningProfile,
    rng: random.Random,
) -> tuple[float, dict[str, float]]:
    """Score one album against the profile; higher is a better pick."""
    key = album.key
    never = key not in profile.all_time_keys
    neglected = key in profile.all_time_keys and key not in profile.quarter_keys
    neglect = 1.0 if never else (0.8 if neglected else 0.0)
    artist = profile.artist_weights.get(fold(album.artist), 0.0)
    genre = max(
        (profile.genre_weights.get(genre, 0.0) for genre in album.genres),
        default=0.0,
    )
    score = 0.55 * neglect + 0.25 * artist + 0.20 * genre + 0.10 * rng.random()
    return score, {
        "neglect": neglect,
        "artist": artist,
        "genre": genre,
        "never": 1.0 if never else 0.0,
    }


def pick_album(
    albums: Iterable[Album],
    profile: ListeningProfile,
    session_recent: Iterable[str] = (),
    oddball_rate: float = ODDBALL_RATE,
    rng: Optional[random.Random] = None,
) -> Optional[AlbumPick]:
    """Filter, score, sample. Returns ``None`` only when there is nothing to pick."""
    rng = rng or random.Random()
    session = set(session_recent)

    candidates = [
        album
        for album in albums
        if album.album_id not in session
        and album.key not in profile.top_album_keys
        and album.key not in profile.quarter_keys
        and album.key not in profile.recent_keys
    ]
    if not candidates:
        # Nothing left that is both neglected and recent-free: keep the
        # hard top-20 / quarter rules, drop only the "recent listens" guard.
        candidates = [
            album
            for album in albums
            if album.album_id not in session
            and album.key not in profile.top_album_keys
            and album.key not in profile.quarter_keys
        ]
    if not candidates:
        # The quarter rule is the last to relax; the top 20 stays excluded.
        candidates = [
            album
            for album in albums
            if album.album_id not in session and album.key not in profile.top_album_keys
        ]
    if not candidates:
        candidates = [album for album in albums if album.album_id not in session]
    if not candidates:
        return None

    scored = []
    for album in candidates:
        score, parts = score_album(album, profile, rng)
        scored.append((score, album, parts))

    oddball = rng.random() < oddball_rate
    if oddball:
        zero_affinity = [
            item for item in scored if item[2]["artist"] == 0 and item[2]["genre"] == 0
        ]
        if zero_affinity:
            scored = zero_affinity
        else:
            oddball = False

    scored.sort(key=lambda item: item[0], reverse=True)
    shortlist = scored[:SHORTLIST]
    weights = [max(score, 0.01) for score, _, _ in shortlist]
    score, album, parts = rng.choices(shortlist, weights=weights, k=1)[0]
    parts = dict(parts)
    parts["oddball"] = 1.0 if oddball else 0.0
    return AlbumPick(
        album_id=album.album_id,
        artist=album.artist,
        album=album.name,
        year=str(album.year or ""),
        reason=_reason(parts),
        score=round(score, 3),
        components=parts,
    )


def pick_local(
    albums: Iterable[Album],
    session_recent: Iterable[str] = (),
    rng: Optional[random.Random] = None,
) -> Optional[AlbumPick]:
    """Fallback when ListenBrainz is unset or unreachable.

    Uses gonic play counts when present: never-played albums first, the 20
    most-played albums excluded, random sampling otherwise. No timestamps are
    available locally, so "long time" degrades to "low play count".
    """
    rng = rng or random.Random()
    session = set(session_recent)
    pool = [album for album in albums if album.album_id not in session]
    if not pool:
        return None

    with_counts = [album for album in pool if album.play_count is not None]
    if len(with_counts) >= 20:
        overplayed = {
            album.album_id
            for album in sorted(
                with_counts, key=lambda album: album.play_count or 0, reverse=True
            )[:20]
        }
        pool = [album for album in pool if album.album_id not in overplayed] or pool

    scored = []
    for album in pool:
        plays = max(int(album.play_count or 0), 0)
        score = 1.0 / (1.0 + plays) + 0.2 * rng.random()
        scored.append((score, album))
    scored.sort(key=lambda item: item[0], reverse=True)
    shortlist = scored[:SHORTLIST]
    weights = [max(score, 0.01) for score, _ in shortlist]
    score, album = rng.choices(shortlist, weights=weights, k=1)[0]
    reason = "never played" if (album.play_count or 0) == 0 else "long-unplayed"
    return AlbumPick(
        album_id=album.album_id,
        artist=album.artist,
        album=album.name,
        year=str(album.year or ""),
        reason=reason,
        score=round(score, 3),
        components={"local_fallback": 1.0},
    )


def _reason(parts: dict[str, float]) -> str:
    base = "never played" if parts.get("never") else "not played in 3 months"
    extras = []
    if parts.get("artist", 0.0) >= 0.5:
        extras.append("artist you play often")
    if parts.get("genre", 0.0) >= 0.5:
        extras.append("genre fits this hour")
    if parts.get("oddball"):
        extras.append("oddball")
    return base + ("; " + "; ".join(extras) if extras else "")
