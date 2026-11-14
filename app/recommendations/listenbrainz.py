"""Minimal, rate-limited ListenBrainz client for the smart-random picker.

Only four public reads are used:
- this quarter's release groups (121 for the reference profile),
- all-time release groups (505),
- genre x hour activity (165 rows),
- the latest listens (100).

A public profile needs no token; ``token`` is optional for private profiles.
Everything is cached in memory by :class:`RecommendationService`.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .models import ListeningProfile
from .text import album_key, canonical_genre, fold

logger = logging.getLogger(__name__)

BASE = "https://api.listenbrainz.org/1"
USER_AGENT = "jukeplayer-backend/0.1 (+https://github.com/kaninfod/jukeplayer_backend)"
TOP_ALBUMS = 20
GENRE_HOUR_WINDOW = 1


class ListenBrainzError(RuntimeError):
    """A ListenBrainz read failed; callers fall back to local data."""


class ListenBrainzClient:
    """Blocking client with the API's one-request-per-second etiquette.

    The lock is shared by every call on this instance, so the profile and
    recent-listen refreshes cannot accidentally exceed the rate limit.
    """

    def __init__(self, username: str, token: str = "", timeout: float = 15.0):
        self.username = str(username or "").strip()
        self.token = str(token or "").strip()
        self.timeout = timeout
        self._lock = threading.Lock()
        self._last_request = 0.0

    def _throttle(self) -> None:
        with self._lock:
            wait = 1.05 - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    def _get(self, path: str, params: dict[str, Any] | None = None, _retry: bool = True) -> dict:
        self._throttle()
        url = f"{BASE}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and _retry:
                reset = exc.headers.get("X-RateLimit-Reset-In")
                delay = min(30.0, float(reset) if reset else 2.0)
                logger.warning("ListenBrainz rate limit hit; retrying in %.0fs", delay)
                time.sleep(delay)
                return self._get(path, params, _retry=False)
            body = exc.read().decode(errors="replace")[:200]
            raise ListenBrainzError(f"ListenBrainz HTTP {exc.code}: {body}") from exc
        except Exception as exc:  # network, timeout, JSON
            raise ListenBrainzError(f"ListenBrainz request failed: {exc}") from exc

    def release_groups(self, range_name: str = "quarter") -> list[dict]:
        data = self._get(
            f"/stats/user/{self.username}/release-groups",
            {"range": range_name, "count": 1000},
        )
        return (data.get("payload") or {}).get("release_groups") or []

    def genre_activity(self, range_name: str = "quarter") -> list[dict]:
        data = self._get(
            f"/stats/user/{self.username}/genre-activity",
            {"range": range_name},
        )
        return (data.get("payload") or {}).get("genre_activity") or []

    def recent_listens(self, count: int = 100) -> list[dict]:
        data = self._get(f"/user/{self.username}/listens", {"count": count})
        return (data.get("payload") or {}).get("listens") or []

    def listens_since(
        self,
        min_ts: int,
        count: int = 1000,
        max_pages: int = 5,
    ) -> list[dict]:
        """All listens with ``listened_at >= min_ts`` (rolling window).

        The stats endpoints are calendar-period and can lag; the listens
        endpoint is immediate. A 90-day window is a few pages at normal
        listening volume and stays well inside the documented "bounded
        recent query" guidance.
        """
        collected: list[dict] = []
        max_ts: int | None = None
        for _ in range(max_pages):
            params: dict[str, Any] = {"count": count}
            if max_ts is not None:
                params["max_ts"] = max_ts
            data = self._get(f"/user/{self.username}/listens", params)
            batch = (data.get("payload") or {}).get("listens") or []
            if not batch:
                break
            collected.extend(batch)
            oldest = int(batch[-1].get("listened_at") or 0)
            if oldest <= min_ts:
                break
            max_ts = oldest
        return [
            listen
            for listen in collected
            if int(listen.get("listened_at") or 0) >= min_ts
        ]


def build_profile(
    quarter: list[dict],
    all_time: list[dict],
    genre_rows: list[dict],
    recent: list[dict] | None = None,
    now: datetime | None = None,
) -> ListeningProfile:
    """Turn the raw API rows into the small profile the picker needs."""
    quarter_keys: set[tuple[str, str]] = set()
    quarter_counts: dict[tuple[str, str], int] = {}
    for row in quarter:
        artist = row.get("artist_name") or ""
        album = row.get("release_group_name") or ""
        if not artist or not album:
            continue
        key = album_key(artist, album)
        quarter_counts[key] = quarter_counts.get(key, 0) + int(row.get("listen_count") or 0)

    quarter_keys = set(quarter_counts)
    counts = sorted(quarter_counts.items(), key=lambda item: item[1], reverse=True)

    all_time_keys: set[tuple[str, str]] = set()
    for row in all_time:
        artist = row.get("artist_name") or ""
        album = row.get("release_group_name") or ""
        if artist and album:
            all_time_keys.add(album_key(artist, album))

    top_album_keys = {key for key, _ in counts[:TOP_ALBUMS]}

    artist_totals: dict[str, int] = {}
    for key, count in counts:
        artist = key[0]
        artist_totals[artist] = artist_totals.get(artist, 0) + count

    current_hour = (now or datetime.now(timezone.utc)).hour
    window = {
        (current_hour + offset) % 24
        for offset in range(-GENRE_HOUR_WINDOW, GENRE_HOUR_WINDOW + 1)
    }
    genre_totals: dict[str, int] = {}
    genre_fallback: dict[str, int] = {}
    for row in genre_rows:
        genre = canonical_genre(row.get("genre"))
        if not genre:
            continue
        count = int(row.get("listen_count") or 0)
        genre_fallback[genre] = genre_fallback.get(genre, 0) + count
        if row.get("hour") in window:
            genre_totals[genre] = genre_totals.get(genre, 0) + count
    genre_weights = _normalise(genre_totals or genre_fallback)
    genre_weights = dict(
        sorted(genre_weights.items(), key=lambda item: item[1], reverse=True)[:6]
    )

    recent_keys: set[tuple[str, str]] = set()
    for listen in recent or []:
        meta = listen.get("track_metadata") or {}
        artist = meta.get("artist_name") or ""
        album = meta.get("release_name") or ""
        if artist and album:
            recent_keys.add(album_key(artist, album))

    return ListeningProfile(
        quarter_keys=quarter_keys,
        all_time_keys=all_time_keys,
        top_album_keys=top_album_keys,
        artist_weights=_normalise(artist_totals),
        genre_weights=genre_weights,
        recent_keys=recent_keys,
        fetched_at=time.monotonic(),
    )


def _normalise(values: dict[str, int]) -> dict[str, float]:
    if not values:
        return {}
    peak = max(values.values()) or 1
    return {key: value / peak for key, value in values.items() if value > 0}
