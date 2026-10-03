"""Cached artist metadata for the kiosk's artist directory.

Per artist: {"name", "dir_id" (the al-* id the directory flow uses),
"count" (the albumCount from gonic's getArtists), "genre" (derived: the
artist's dominant album-genre from the collection's file tags)}.
Plus the genre chips list (getGenres: value, albumCount, songCount).

Lifecycle: refresh() loads everything with FOUR gonic calls, independent
of library size:
  1. getMusicDirectory id=al-1   → artist dirs (al-* id + name)
  2. getAlbumList2 byName        → every album, rows carry artist + genre
  3. getArtists                  → albumCount per artist (entity space)
  4. getGenres                   → the chip list
The per-artist dominant-genre vote happens in a local loop over call #2
rows (the old per-artist getMusicDirectory+getAlbum storm measured
~1,600 calls for this collection). Chips are pre-filled by refresh();
genre_chip()'s lazy getMusicDirectory path only survives as the fallback
when the album list call failed.

Warmed at app startup and by the config's "refresh subsonic data"
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
        """Load artist facts from gonic; the count join is by artist-name
        (the al-*/ar-* id spaces don't overlap — getMusicDirectory resolves
        the directory flow's al-* ids, getArtists speaks entity ar-*).
        Returns the summary counts."""
        directory = self.subsonic.list_artists()          # [{id, name}]
        counts = {e["name"]: e.get("albumCount", 0)
                  for e in self.subsonic.artists_with_counts()}
        genres = self.subsonic.list_genres()

        # the dominant-genre vote: one pass over the single-call album list;
        # rows carry the album's primary genre — the same attribution the
        # genre chips (getGenres) count by, so an artist chip always agrees
        # with that genre's album grid membership
        try:
            flat_albums = self.subsonic.list_all_albums()
            chips_ready = True
        except Exception as e:
            logger.warning(f"ArtistMetadata: album-list call failed — genre chips "
                           f"fall back to the lazy per-artist path ({e})")
            flat_albums, chips_ready = [], False

        votes: Dict[str, Counter] = {}
        for album in flat_albums:
            name = album.get("artist") or ""
            if name and album.get("genre"):
                votes.setdefault(name, Counter())[album["genre"]] += 1

        artists = {}
        for a in directory:
            name = a.get("name") or ""
            entry = {
                "name": name,
                "dir_id": a.get("id"),
                "count": counts.get(name, 0),
            }
            if chips_ready:
                counter = votes.get(name)
                entry["genre"] = counter.most_common(1)[0][0] if counter else None
            artists[name] = entry
        self._artists = artists
        self._genres = genres
        logger.info(f"ArtistMetadata: refreshed {len(artists)} artists, {len(genres)} genres")
        return {"artists": len(artists), "genres": len(genres)}

    def artists(self) -> List[dict]:
        return list(self._artists.values())

    def get(self, name: str) -> Optional[dict]:
        return self._artists.get(name)

    def genre_chip(self, name: str) -> Optional[str]:
        """The artist's display genre — the refresh()-pre-filled value.
        Falls back to the lazy per-artist derivation (then cached) only if
        refresh could not fill it (album-list call failed)."""
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