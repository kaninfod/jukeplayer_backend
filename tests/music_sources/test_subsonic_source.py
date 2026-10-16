"""SubsonicSource's seam contract: album → a namespaced queue, stream_url,
covers, scrobble, readiness — mocked at the transport (no real gonic)."""
from unittest.mock import MagicMock

import pytest

from app.music_sources.subsonic import SubsonicSource


def make_source():
    config = MagicMock()
    config.SUBSONIC_URL = "http://gonic:4747"
    config.SUBSONIC_USER = "jukebox"
    config.SUBSONIC_PASS = "pw"
    config.SUBSONIC_CLIENT = "test"
    config.SUBSONIC_API_VERSION = "1.16.1"
    config.HTTP_REQUEST_TIMEOUT = 10
    return SubsonicSource(config)


def _album_payload(name="Physical Graffiti", artist="Led Zeppelin", year=1975):
    return {
        "subsonic-response": {"album": {
            "id": "al-99", "name": name, "artist": artist, "year": year,
            "song": [
                {"id": "tr-8880", "title": "Custard Pie", "duration": 253, "track": 1},
                {"id": "tr-8881", "title": "The Rover", "duration": 338, "track": 2},
            ],
        }},
    }


def test_load_album_namespaces_ids_and_carries_metadata(monkeypatch):
    src = make_source()
    monkeypatch.setattr(src.api, "_api_request", lambda *a, **k: _wrap(_album_payload()))

    album = src.load_album("al-99")

    assert album.album_id == "subsonic:al-99"
    assert album.title == "Physical Graffiti"
    assert album.artist == "Led Zeppelin"
    assert album.year == "1975"
    assert album.cover_url == "/api/subsonic/cover/al-99"    # the gonic-faculty proxy contract, unchanged
    assert [t.track_id for t in album.tracks] == ["subsonic:tr-8880", "subsonic:tr-8881"]
    assert album.tracks[0].title == "Custard Pie"
    assert album.tracks[0].duration == "253"
    assert album.tracks[0].track_number == 1


def test_load_album_missing_raises(monkeypatch):
    src = make_source()
    monkeypatch.setattr(src.api, "_api_request", lambda *a, **k: _wrap({"subsonic-response": {"album": {}}}))
    with pytest.raises(ValueError, match="not found"):
        src.load_album("al-ghost")


def test_load_album_empty_raises(monkeypatch):
    src = make_source()
    monkeypatch.setattr(src.api, "_api_request",
                        lambda *a, **k: _wrap({"subsonic-response": {"album": {"name": "x", "artist": "y", "year": 1975, "song": []}}}))
    with pytest.raises(ValueError, match="No tracks"):
        src.load_album("al-empty")


def test_stream_url_unqualifies_the_queue_id():
    src = make_source()
    spec = src.stream_url("subsonic:tr-8880")
    assert spec.url.startswith("http://gonic:4747/rest/stream?")
    assert "id=tr-8880" in spec.url
    assert "u=jukebox" in spec.url and "t=" in spec.url
    assert "f=" not in spec.url          # binary endpoints carry no format param
    assert spec.external is False


def test_is_ready_probes_ping(monkeypatch):
    src = make_source()
    monkeypatch.setattr(src.api, "_api_request", lambda *a, **k: _wrap({"subsonic-response": {"status": "ok"}}))
    assert src.is_ready() is True

    def boom(*a, **k):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(src.api, "_api_request", boom)
    assert src.is_ready() is False


def test_scrobble_strips_the_namespace(monkeypatch):
    src = make_source()
    seen = {}
    monkeypatch.setattr(src, "scrobble_now_playing", lambda tid: seen.setdefault("id", tid))

    src.scrobble("subsonic:tr-42")

    assert seen["id"] == "tr-42"


def _wrap(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    return resp