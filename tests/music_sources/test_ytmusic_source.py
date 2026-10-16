"""YTMusicSource's seam contract — the PUBLIC (un-authed) mode is the
active path; the ytmusicapi client is mocked, no network."""
import time as time_mod
from unittest.mock import MagicMock

import pytest

from app.music_sources.base import SourceCapability
from app.music_sources.ytmusic import YTMusicSource, duration_to_seconds


def make_source(**extra):
    src = YTMusicSource({"enabled": True, **extra})   # no token: the public mode
    client = MagicMock()
    src._client = client
    return src, client


def test_duration_to_seconds_handles_ytm_forms():
    assert duration_to_seconds(253) == "253"
    assert duration_to_seconds("3:53") == "233"
    assert duration_to_seconds("1:02:03") == "3723"
    assert duration_to_seconds(None) == "0"
    assert duration_to_seconds("nonsense") == "0"


def test_public_mode_constructs_without_token_or_credentials():
    """The auth-free design: `{"enabled": True}` is a complete config."""
    assert YTMusicSource({"enabled": True}).is_ready() is True


def test_album_id_disambiguation():
    src, client = make_source()
    client.get_album.return_value = {
        "title": "Physical Graffiti", "artists": [{"name": "Led Zeppelin"}], "year": 1975,
        "thumbnails": [{"url": "http://thumb/low"}, {"url": "http://thumb/big", "width": 1200}],
        "tracks": [
            {"videoId": "v1", "title": "Custard Pie", "duration_seconds": 253,
             "artists": [{"name": "Led Zeppelin"}], "albumTrackIndex": 1},
            {"title": "no-video-id row"},   # skipped (no playable id)
        ],
    }
    album = src.load_album("MPREb_someAlbum")
    assert album.album_id == "ytmusic:MPREb_someAlbum"
    assert album.cover_url == "http://thumb/big"          # the largest thumb wins
    assert [t.track_id for t in album.tracks] == ["ytmusic:v1"]
    assert album.tracks[0].duration == "253"
    assert album.tracks[0].track_number == 1


def test_playlist_id_shape_uses_get_playlist():
    src, client = make_source()
    client.get_playlist.return_value = {
        "title": "A Summer Evening", "owner": {"name": "martin"},
        "thumbnails": [{"url": "http://t/1", "width": 300}],
        "tracks": [
            {"videoId": "a1", "title": "One", "duration": "2:10", "artists": [{"name": "Bird"}]},
            {"videoId": "a2", "title": "Two", "duration": "3:00", "artists": [{"name": "Fish"}]},
        ],
    }
    album = src.load_album("OLAK5uy_playlistId1")
    client.get_album.assert_not_called()
    client.get_playlist.assert_called_once_with("OLAK5uy_playlistId1")
    assert album.artist == "martin"
    assert [t.artist for t in album.tracks] == ["Bird", "Fish"]   # per-track artists survive
    assert [t.duration for t in album.tracks] == ["130", "180"]


def test_unknown_album_id_shape_raises():
    src, _ = make_source()
    with pytest.raises(ValueError, match="Unsupported ytmusic album id"):
        src.load_album("dQw4w9WgXcQ")   # a bare video id is not an album


def test_stream_url_is_the_watch_page():
    src, _ = make_source()
    spec = src.stream_url("ytmusic:v7")
    assert spec.url == "https://www.youtube.com/watch?v=v7"
    assert spec.external is True


def test_search_maps_hits_and_skips_idless_rows():
    src, client = make_source()
    client.search.return_value = [
        {"resultType": "song", "videoId": "v1", "title": "T", "artists": [{"name": "A"}], "duration": 200},
        {"resultType": "album", "browseId": "MPREb_x", "playlistId": "OLAK5uy_p",
         "title": "Al", "artists": [{"name": "Artist"}]},
        {"resultType": "song", "title": "no id row"},   # skipped
    ]
    hits = src.search("any")
    assert hits[0] == dict(kind="track", track_id="ytmusic:v1", title="T", artist="A", duration="200")
    assert hits[1]["album_id"] == "ytmusic:MPREb_x"
    assert hits[1]["playlist_id"] == "OLAK5uy_p"
    assert len(hits) == 2


def test_cover_art_fetches_and_returns_bytes(monkeypatch):
    src, client = make_source()
    client.get_album.return_value = {"thumbnails": [{"url": "https://t/x", "width": 900}]}
    fake_resp = MagicMock(content=b"jpg-bytes")
    fake_resp.raise_for_status = MagicMock()
    import requests as requests_mod
    monkeypatch.setattr(requests_mod, "get", lambda url, timeout=0: fake_resp)

    assert src.cover_art("MPREb_some") == b"jpg-bytes"


def test_capabilities_declared():
    src, _ = make_source()
    assert SourceCapability.SEARCH in src.capabilities
    assert SourceCapability.COVER_ART in src.capabilities
    assert SourceCapability.SCROBBLE not in src.capabilities
    assert SourceCapability.BROWSE not in src.capabilities
    assert src.scrobble("ytmusic:v") is False


def test_token_present_switches_to_authed_mode():
    """The dual mode: a token-carrying config keeps the token; the client
    would build authed on its first use (the future/premium lane)."""
    src = YTMusicSource({"enabled": True, "client_id": "c", "client_secret": "s",
                         "token": {"access_token": "a", "refresh_token": "r",
                                   "scope": "s", "token_type": "Bearer",
                                   "expires_at": time_mod.time() + 3600}})
    assert src._token.get("access_token") == "a"