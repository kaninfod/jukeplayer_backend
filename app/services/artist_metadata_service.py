"""Cached artist metadata for the kiosk's artist directory.

Per artist: {"name", "dir_id" (the al-* id the directory flow uses),
"count" (the albumCount from gonic's getArtists), "genre" (derived: the
artist's dominant album-genre from the collection's file tags)}.
Plus the genre chips list (getGenres: value, albumCount, songCount).

Lifecycle: refresh() loads everything (blocking gonic calls — run in a
thread); warmed at app startup and by the config's "refresh subsonic data"
button. list_artists' old @lru_cache is retired — THIS is the cache now."""

import logging
from collections import Counter
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ArtistMetadataService:
    def __init__(self, subsonic_service):
        self.subsonic = subsonic_service
        self._artists: Dict[str, dict] = {}
        self._genres: List[dict] = []

    def refresh(self) -> dict:
        """Load artist facts from gonic; the JOIN is by artist-name (the two
        id-spaces (al-*/ar-*) share names). Returns the summary counts."""
        directory = self.subsonic.list_artists()          # [{id, name}]
        entities = self.subsonic.artists_with_counts()    # [{id, name, albumCount}]
        counts = {e["name"]: e.get("albumCount", 0) for e in entities}
        artists = {}
        for a in directory:
            name = a.get("name") or ""
            artists[name] = {
                "name": name,
                "dir_id": a.get("id"),
                "count": counts.get(name, 0),
            }
        genres = self.subsonic.list_genres()
        # artist genre: the dominant album-genre (getGenres' rows are per
        # genre; per-ARTIST requires the artist→albums→genre path — derived
        # lazily per artist on display, cached here on first use)
        self._artists = artists
        self._genres = genres
        logger.info(f"ArtistMetadata: refreshed {len(artists)} artists, {len(genres)} genres")
        return {"artists": len(artists), "genres": len(genres)}

    def artists(self) -> List[dict]:
        return list(self._artists.values())

    def get(self, name: str) -> Optional[dict]:
        return self._artists.get(name)

    def genre_chip(self, name: str) -> Optional[str]:
        """The artist's display genre: their dominant album-genre (cached)."""
        a = self._artists.get(name)
        if not a:
            return None
        if "genre" in a:
            return a["genre"]
        genre = self.subsonic.artist_dominant_genre(a.get("dir_id"))
        a["genre"] = genre
        return genre

    def genres(self) -> List[dict]:
        return list(self._genres)

    def counts_by_genre(self) -> Dict[str, int]:
        return {g["value"]: g.get("albumCount", 0) for g in self._genres}
