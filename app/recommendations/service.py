"""The in-memory smart-random service.

No database, no cache files, no new persistent state: the album catalog and
the ListenBrainz profile live for the life of the process and are refreshed on
a TTL. The only persistent setting is the ListenBrainz username/token in the
existing config store.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from typing import Any, Optional

from .listenbrainz import ListenBrainzClient, build_profile
from .models import Album, AlbumPick
from .picker import ODDBALL_RATE, pick_album, pick_local, pick_neglected, pick_random
from .text import canonical_genre

logger = logging.getLogger(__name__)

ALBUM_TTL = 3600.0
PROFILE_TTL = 6 * 3600.0
RECENT_TTL = 120.0
FAILURE_BACKOFF = 60.0
WINDOW_DAYS = 90
MODES = ("smart", "random", "neglected")


def normalize_mode(mode: str | None) -> str:
    """Coerce a transport value to a known picker mode (default smart)."""
    value = str(mode or "smart").strip().lower()
    return value if value in MODES else "smart"


class RecommendationService:
    """Pick a neglected owned album that fits the current listening context."""

    def __init__(self, music_sources, config_service, *, oddball_rate: float = ODDBALL_RATE):
        self.music_sources = music_sources
        self.config_service = config_service
        self.oddball_rate = oddball_rate
        self._albums: list[Album] = []
        self._albums_at = 0.0
        self._profile = None
        self._profile_at = 0.0
        self._profile_next_try = 0.0
        self._recent: list[dict] | None = None
        self._recent_at = 0.0
        self._recent_picks: deque[str] = deque(maxlen=10)
        self._lb_signature: tuple[str, str] | None = None
        self._lb_client: ListenBrainzClient | None = None
        self._warming = False
        self._lock = asyncio.Lock()

    # --- public API ---------------------------------------------------------
    async def warm(self) -> None:
        """Build the in-memory catalog/profile off the startup path."""
        if self._warming:
            return
        self._warming = True
        try:
            await self._ensure_albums()
            await self._ensure_profile()
            await self._ensure_recent()
        except Exception as exc:  # never block startup on the picker
            logger.warning("[recommendations] warm-up failed: %s", exc)
        finally:
            self._warming = False

    async def pick(self, device_name: str | None = None,
                   mode: str = "smart") -> Optional[AlbumPick]:
        """Pick an album; returns None only when there is nothing to play.

        ``mode`` is ``smart`` (the profile-weighted picker), ``random``
        (uniform over the whole catalog) or ``neglected`` (uniform over the
        hard-exclusion pool, no affinity). The default is unchanged.
        """
        mode = normalize_mode(mode)
        async with self._lock:
            await self._ensure_albums()
            if not self._albums:
                logger.warning("[recommendations] no albums in the catalog")
                return None

            if mode == "random":
                pick = pick_random(
                    self._albums,
                    session_recent=self._recent_picks,
                    rng=random.Random(),
                )
            elif mode == "neglected":
                try:
                    await self._ensure_profile()
                except Exception as exc:
                    logger.warning("[recommendations] ListenBrainz unavailable, using local fallback: %s", exc)
                    self._profile = None
                if self._profile is not None:
                    try:
                        await self._ensure_recent()
                    except Exception as exc:
                        logger.warning("[recommendations] recent listens unavailable: %s", exc)
                    pick = pick_neglected(
                        self._albums,
                        self._profile,
                        session_recent=self._recent_picks,
                        rng=random.Random(),
                    )
                else:
                    pick = pick_local(
                        self._albums,
                        session_recent=self._recent_picks,
                        rng=random.Random(),
                    )
            else:
                try:
                    await self._ensure_profile()
                except Exception as exc:
                    logger.warning("[recommendations] ListenBrainz unavailable, using local fallback: %s", exc)
                    self._profile = None

                if self._profile is not None:
                    try:
                        await self._ensure_recent()
                    except Exception as exc:
                        logger.warning("[recommendations] recent listens unavailable: %s", exc)
                    pick = pick_album(
                        self._albums,
                        self._profile,
                        session_recent=self._recent_picks,
                        oddball_rate=self.oddball_rate,
                        rng=random.Random(),
                    )
                else:
                    pick = pick_local(
                        self._albums,
                        session_recent=self._recent_picks,
                        rng=random.Random(),
                    )

            if pick is not None:
                self._recent_picks.append(pick.album_id)
                logger.info(
                    "[recommendations] %s pick for %s: %s - %s (%s, score %.3f)",
                    mode,
                    device_name or "default",
                    pick.artist,
                    pick.album,
                    pick.reason,
                    pick.score,
                )
            return pick

    # --- data loading -------------------------------------------------------
    def _source(self):
        if self.music_sources is None:
            return None
        try:
            return self.music_sources.get(None)
        except Exception:
            return None

    async def _ensure_albums(self) -> None:
        if self._albums and (time.monotonic() - self._albums_at) < ALBUM_TTL:
            return
        source = self._source()
        if source is None or not hasattr(source, "list_all_albums"):
            self._albums = []
            self._albums_at = time.monotonic()
            return
        raw = await asyncio.to_thread(source.list_all_albums)
        albums = [album for album in (_album_from_raw(item) for item in raw or []) if album]
        self._albums = albums
        self._albums_at = time.monotonic()
        logger.info("[recommendations] catalog loaded: %d albums", len(albums))

    def _client(self) -> ListenBrainzClient | None:
        cfg = self.config_service.listenbrainz() if self.config_service else {}
        username = str(cfg.get("username") or "").strip()
        token = str(cfg.get("token") or "").strip()
        signature = (username, token)
        if signature != self._lb_signature:
            # Credentials changed (first setup or an edit): drop the profile
            # so the next pick uses the new account immediately.
            self._lb_signature = signature
            self._lb_client = ListenBrainzClient(username, token) if username else None
            self._profile = None
            self._profile_at = 0.0
            self._recent = None
            self._recent_at = 0.0
        return self._lb_client

    async def _ensure_profile(self) -> None:
        client = self._client()
        if client is None:
            self._profile = None
            return
        if self._profile is not None and (time.monotonic() - self._profile_at) < PROFILE_TTL:
            return
        if time.monotonic() < self._profile_next_try:
            return

        def fetch():
            min_ts = int(time.time()) - WINDOW_DAYS * 86400
            listens = client.listens_since(min_ts)
            all_time = client.release_groups("all_time")
            genres = client.genre_activity("quarter")
            return listens, all_time, genres

        try:
            listens, all_time, genres = await asyncio.to_thread(fetch)
        except Exception:
            self._profile = None
            self._profile_next_try = time.monotonic() + FAILURE_BACKOFF
            raise

        if not listens and not all_time:
            logger.warning(
                "[recommendations] ListenBrainz returned no listens or release stats for %s",
                client.username,
            )
            self._profile = None
            self._profile_next_try = time.monotonic() + FAILURE_BACKOFF
            return

        profile = build_profile(
            _rows_from_listens(listens),
            all_time,
            genres,
            listens[:100],
        )
        self._profile = profile
        self._profile_at = time.monotonic()
        self._profile_next_try = 0.0
        logger.info(
            "[recommendations] profile loaded: %d listens in %d days, %d recent albums, %d all-time albums, %d genres",
            len(listens),
            WINDOW_DAYS,
            len(profile.quarter_keys),
            len(profile.all_time_keys),
            len(profile.genre_weights),
        )

    async def _ensure_recent(self) -> None:
        client = self._client()
        if client is None:
            return
        if self._recent is not None and (time.monotonic() - self._recent_at) < RECENT_TTL:
            return
        recent = await asyncio.to_thread(client.recent_listens, 100)
        self._recent = recent
        self._recent_at = time.monotonic()
        if self._profile is not None:
            recent_only = build_profile([], [], [], recent)
            self._profile.recent_keys = recent_only.recent_keys


def _album_from_raw(raw: Any) -> Album | None:
    """Map one gonic/Subsonic album row into the picker's album."""
    if not isinstance(raw, dict):
        return None
    album_id = raw.get("id") or raw.get("albumId")
    name = raw.get("name") or raw.get("title") or raw.get("album")
    artist = raw.get("artist")
    if not album_id or not name or not artist:
        return None

    genres: list[str] = []
    raw_genres = raw.get("genres")
    if isinstance(raw_genres, list):
        for entry in raw_genres:
            value = entry.get("name") if isinstance(entry, dict) else entry
            if value:
                genres.append(canonical_genre(value))
    if not genres and raw.get("genre"):
        for value in str(raw["genre"]).replace("/", ";").split(";"):
            if value.strip():
                genres.append(canonical_genre(value))

    play_count = raw.get("playCount")
    try:
        play_count = int(play_count) if play_count is not None else None
    except (TypeError, ValueError):
        play_count = None

    return Album(
        album_id=str(album_id),
        artist=str(artist),
        name=str(name),
        year=str(raw.get("year") or ""),
        genres=tuple(dict.fromkeys(genre for genre in genres if genre)),
        play_count=play_count,
    )


def _rows_from_listens(listens: list[dict]) -> list[dict]:
    """Turn raw listens into the release-group rows ``build_profile`` expects.

    One row per listen (``listen_count=1``); ``build_profile`` aggregates the
    duplicate keys, so the top albums and artist weights are exact for the
    rolling window.
    """
    rows = []
    for listen in listens or []:
        meta = listen.get("track_metadata") or {}
        artist = meta.get("artist_name") or ""
        album = meta.get("release_name") or ""
        if artist and album:
            rows.append(
                {
                    "artist_name": artist,
                    "release_group_name": album,
                    "listen_count": 1,
                }
            )
    return rows
