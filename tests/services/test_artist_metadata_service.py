"""Unit tests for ArtistMetadataService — the kiosk artist-directory cache.

The contract this locks in (all measured on gonic 0.22):
  - refresh() = 4 gonic calls total, independent of library size; the
    dominant-genre vote is a local loop over the single-call album list
  - counts join by name from getArtists' albumCount
  - a failed album-list call degrades to the lazy per-artist chip path
    instead of failing the whole refresh"""
import pytest

from app.services.artist_metadata_service import ArtistMetadataService


class FakeSubsonic:
    """Call-counting stand-in — no gonic in unit tests."""

    def __init__(self, albums):
        self._albums = albums
        self.calls: dict = {}
        self.albums_should_fail = False

    def list_artists(self):
        self.calls["list_artists"] = self.calls.get("list_artists", 0) + 1
        return [
            {"id": "al-7", "name": "Aerosmith"},
            {"id": "al-3", "name": "Adele"},
            {"id": "al-9", "name": "ZZ Top"},
        ]

    def artists_with_counts(self):
        self.calls["artists_with_counts"] = self.calls.get("artists_with_counts", 0) + 1
        return [
            {"id": "ar-2", "name": "Aerosmith", "albumCount": 1},
            {"id": "ar-3", "name": "Adele", "albumCount": 2},
            {"id": "ar-9", "name": "ZZ Top", "albumCount": 0},
        ]

    def list_genres(self):
        self.calls["list_genres"] = self.calls.get("list_genres", 0) + 1
        return [{"value": "Rock", "albumCount": 1, "songCount": 12},
                {"value": "Pop", "albumCount": 2, "songCount": 24}]

    def list_all_albums(self, page_size: int = 10000):
        self.calls["list_all_albums"] = self.calls.get("list_all_albums", 0) + 1
        if self.albums_should_fail:
            raise RuntimeError("gonic down")
        return self._albums

    def artist_dominant_genre(self, dir_id):
        self.calls["artist_dominant_genre"] = self.calls.get("artist_dominant_genre", 0) + 1
        return "Blues"  # the lazy fallback's voice


ALBUMS = [
    {"id": "al-5", "name": "Rocks", "artist": "Aerosmith", "genre": "Rock"},
    {"id": "al-3", "name": "19", "artist": "Adele", "genre": "Pop"},
    {"id": "al-4", "name": "21", "artist": "Adele", "genre": "Pop"},
    {"id": "al-8", "name": "Tagless", "artist": "Adele", "genre": ""},
]


def test_refresh_derives_dominant_genre_in_four_calls():
    svc = ArtistMetadataService(FakeSubsonic(ALBUMS))
    summary = svc.refresh()

    assert summary == {"artists": 3, "genres": 2}
    fake = svc.subsonic
    # exactly the four warm-up calls — no per-artist storm
    assert sum(fake.calls.values()) == 4
    assert fake.calls["list_all_albums"] == 1
    assert fake.calls.get("artist_dominant_genre", 0) == 0

    a = svc.artists()
    by_name = {x["name"]: x for x in a}
    assert by_name["Aerosmith"]["genre"] == "Rock"
    assert by_name["Adele"]["genre"] == "Pop"
    assert by_name["ZZ Top"]["genre"] is None          # no albums, no votes
    assert by_name["Aerosmith"]["count"] == 1          # joined from getArtists
    assert by_name["Adele"]["count"] == 2

    # chips deliver straight from the cache, no gonic touch
    assert svc.genre_chip("Aerosmith") == "Rock"
    assert svc.genre_chip("Ghost") is None             # unknown artist


def test_failed_album_list_degrades_to_lazy_chips():
    fake = FakeSubsonic(ALBUMS)
    fake.albums_should_fail = True
    svc = ArtistMetadataService(fake)

    summary = svc.refresh()
    assert summary == {"artists": 3, "genres": 2}      # refresh still succeeds

    # no genre key → the lazy fallback answers on first chip request
    assert "genre" not in svc.get("Aerosmith")
    assert svc.genre_chip("Aerosmith") == "Blues"
    assert fake.calls["artist_dominant_genre"] == 1    # now cached in-memory
    assert svc.genre_chip("Aerosmith") == "Blues"
    assert fake.calls["artist_dominant_genre"] == 1