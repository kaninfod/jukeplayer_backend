"""Unit tests for the genre-enrichment pure core (selection/normalization/IO)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root for scripts namespace pkg

import pytest  # noqa: E402

from scripts.genre_enrichment import (  # noqa: E402
    genre_join,
    normalize_genres,
    parse_mbids_from_id3,
    parse_mbids_from_vorbis,
    qualifying,
    select_genres,
)


def make_id3_txxx(musicbrainz_release_group_id=None, musicbrainz_artist_id=None):
    from mutagen.id3 import ID3, TXXX
    tags = ID3()
    if musicbrainz_release_group_id:
        tags.add(TXXX(encoding=1, desc="MusicBrainz Release Group Id", text=[musicbrainz_release_group_id]))
    if musicbrainz_artist_id:
        tags.add(TXXX(encoding=1, desc="MusicBrainz Artist Id", text=[musicbrainz_artist_id]))
    return tags


def test_parse_mbids_from_id3():
    tags = make_id3_txxx("rg-123", "ar-456")
    assert parse_mbids_from_id3(tags) == ("rg-123", "ar-456")
    assert parse_mbids_from_id3(None) == (None, None)


def test_parse_mbids_tolerates_descriptions():
    from mutagen.id3 import ID3, TXXX
    tags = ID3()
    tags.add(TXXX(encoding=1, desc="MusicBrainz Release Group Id ", text=["rg-1"]))
    tags.add(TXXX(encoding=1, desc="MusicBrainz Album Artist Id", text=["ar-2"]))
    assert parse_mbids_from_id3(tags) == ("rg-1", "ar-2")


def test_parse_vorbis_multivalue():
    class FakeTags(dict):
        pass
    tags = FakeTags({
        "musicbrainz_releasegroupid": ["rg-9"],
        "musicbrainz_artistid": ["ar-8"],
    })
    assert parse_mbids_from_vorbis(tags) == ("rg-9", "ar-8")
    assert parse_mbids_from_vorbis(None) == (None, None)


def test_qualifying_orders_by_votes_desc():
    genres = [
        {"name": "rock", "count": 10, "vote_count": 12},
        {"name": "pop", "count": 50, "vote_count": 2},   # below threshold
        {"name": "jazz", "count": 7, "vote_count": 30},
        {"name": "", "vote_count": 99},                   # no name
    ]
    assert qualifying(genres, 3) == ["jazz", "rock"]


def test_select_genres_prefers_release_group_then_artist_then_lastfm():
    rg = [{"name": "fusion", "count": 5, "vote_count": 8}]
    artist = [{"name": "jazz", "count": 40, "vote_count": 90}]
    genres, source = select_genres(rg, artist, ["Smooth Jazz"])
    assert genres == ["Fusion"] and source == "musicbrainz_release_group"

    genres, source = select_genres([], artist, ["Smooth Jazz"])
    assert genres == ["Jazz"] and source == "musicbrainz_artist"

    genres, source = select_genres([], [], ["Seen Live", "Smooth Jazz", "Jazz"])
    # 'seen live' filtered upstream in real flow; here it just passes through
    assert genres == ["Seen Live", "Smooth Jazz", "Jazz"] and source == "lastfm"

    assert select_genres([], [], []) == ([], "none")


def test_normalize_dedupe_and_titlecase():
    assert normalize_genres(["jazz", "Jazz", "JAZZ ", "prog rock", ""]) == ["Jazz", "Prog Rock"]


def test_genre_join():
    assert genre_join(["jazz-rock", "Jazz"]) == "Jazz-Rock; Jazz"
    assert genre_join([]) is None


def test_select_genres_caps_at_max():
    rg = [{"name": f"g{i}", "count": 10, "vote_count": 10 + i} for i in range(6)]
    genres, source = select_genres(rg, [], [], max_genres=3)
    assert len(genres) == 3 and source == "musicbrainz_release_group"