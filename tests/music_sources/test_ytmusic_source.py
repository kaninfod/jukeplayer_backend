"""YTMusicSource — the second citizen's seam contract (mocked at the
ytmusicapi client; no network)."""
from unittest.mock import MagicMock

import pytest

from app.music_sources.ytmusic import YTMusicSource, duration_to_seconds


def make_source(**extra):
    cfg = {"enabled": True, "client_id": "cid", "client_secret": "sec",
           "token": {"access_token": "x", "refresh_token": "y"},
           **extra}
    src = YTMusicSource(cfg)
    src._client = MagicMock()          # the client is mocked — no network
    src._client_token = cfg["token"]
    return src


def test_duration_to_seconds_handles_ytm_forms():
    assert duration_to_seconds(253) == "253"
    assert duration_to_seconds("3:53") == "233"
    assert duration_to_seconds("1:02:03") == "3723"
    assert duration_to_seconds(None) == "0"
    assert duration_to_seconds("nonsense") == "0"


def test_album_id_disambiguation():
    src = make_source()
    src._client.get_album.return_value = {
        "title": "Physical Graffiti", "artists": [{"name": "Led Zeppelin"}], "year": 1975,
        "thumbnails": [{"url": "http://thumb/low"}, {"url": "http://thumb/big", "width": 1200}],
        "tracks": [
            {"videoId": "v1", "title": "Custard Pie", "duration_seconds": 253,
             "artists": [{"name": "Led Zeppelin"}], "albumTrackIndex": 1},
            {"title": "no-video-id row"},   # rows without a videoId are skipped
        ],
    }
    album = src.load_album("MPREb_someAlbum")
    assert album.album_id == "ytmusic:MPREb_someAlbum"
    assert album.cover_url == "http://thumb/big"          # the largest thumb wins
    assert [t.track_id for t in album.tracks] == ["ytmusic:v1"]
    assert album.tracks[0].duration == "253"


def test_playlist_id_shape_uses_get_playlist():
    src = make_source()
    src._client.get_playlist.return_value = {
        "title": "A Summer Evening", "owner": {"name": "martin"},
        "thumbnails": [{"url": "http://t/1", "width": 300}],
        "tracks": [
            {"videoId": "a1", "title": "One", "duration": "2:10", "artists": [{"name": "Bird"}]},
            {"videoId": "a2", "title": "Two", "duration": "3:00", "artists": [{"name": "Fish"}]},
        ],
    }
    album = src.load_album("OLAK5uy_playlistId1")
    src._client.get_album.assert_not_called()
    src._client.get_playlist.assert_called_once_with("OLAK5uy_playlistId1")
    assert album.artist == "martin"
    assert [t.artist for t in album.tracks] == ["Bird", "Fish"]   # per-track artists survive
    assert [t.duration for t in album.tracks] == ["130", "180"]


def test_unknown_album_id_shape_raises():
    src = make_source()
    with pytest.raises(ValueError, match="Unsupported ytmusic album id"):
        src.load_album("dQw4w9WgXcQ")   # a bare video id is not an album


def test_stream_url_is_the_watch_page():
    src = make_source()
    spec = src.stream_url("ytmusic:v7")
    assert spec.url == "https://www.youtube.com/watch?v=v7"
    assert spec.external is True


def test_cover_art_fetches_and_returns_bytes(monkeypatch):
    src = make_source()
    src._client.get_album.return_value = {"thumbnails": [{"url": "https://t/x", "width": 900}]}
    fake_resp = MagicMock(content=b"jpg-bytes")
    fake_resp.raise_for_status = MagicMock()
    import requests as requests_mod
    monkeypatch.setattr(requests_mod, "get", lambda url, timeout=0: fake_resp)

    assert src.cover_art("MPREb_some") == b"jpg-bytes"


def test_capabilities_declared():
    src = make_source()
    from app.music_sources.base import SourceCapability
    assert SourceCapability.SEARCH in src.capabilities
    assert SourceCapability.COVER_ART in src.capabilities
    assert SourceCapability.SCROBBLE not in src.capabilities
    assert SourceCapability.BROWSE not in src.capabilities
    assert src.scrobble("ytmusic:v") is False