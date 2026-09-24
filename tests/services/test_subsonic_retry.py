"""Tests for SubsonicService retry behaviour and scrobble semantics."""
import pytest
import requests
from unittest.mock import MagicMock

from app.services.subsonic_service import SubsonicService


def make_service():
    config = MagicMock()
    config.SUBSONIC_URL = "http://gonic:80"
    config.SUBSONIC_USER = "u"
    config.SUBSONIC_PASS = "p"
    config.SUBSONIC_CLIENT = "test"
    config.SUBSONIC_API_VERSION = "1.16.1"
    config.HTTP_REQUEST_TIMEOUT = 10
    return SubsonicService(config)


def _resp_json(payload):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    resp.content = b"x"
    return resp


def test_transient_connection_error_is_retried(monkeypatch):
    svc = make_service()
    calls = []

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"subsonic-response": {"status": "ok"}}

    def flaky_get(url, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise requests.exceptions.ConnectionError("RemoteDisconnected('Remote end closed connection')")
        return _resp_json({"subsonic-response": {"status": "ok"}})

    monkeypatch.setattr(requests, "get", flaky_get)
    monkeypatch.setattr("app.services.subsonic_service.time.sleep", lambda s: None)

    result = svc._api_request("ping")

    assert result.json()["subsonic-response"]["status"] == "ok"
    assert len(calls) == 2  # one retry


def test_transient_error_retries_exhausted_then_raises(monkeypatch):
    svc = make_service()

    def always_fails(url, **kwargs):
        raise requests.exceptions.ConnectionError("RemoteDisconnected('Remote end closed connection')")

    monkeypatch.setattr(requests, "get", always_fails)
    monkeypatch.setattr("app.services.subsonic_service.time.sleep", lambda s: None)

    import pytest as _pytest
    try:
        svc._api_request("getAlbum", retries=1)
        raised = False
    except requests.exceptions.ConnectionError:
        raised = True
    assert raised


def test_http_error_not_retried(monkeypatch):
    svc = make_service()
    calls = []

    def http_404(url, **kwargs):
        calls.append(1)
        resp = MagicMock()
        resp.status_code = 404
        http_err = requests.exceptions.HTTPError("404")
        http_err.response = resp
        raise http_err

    monkeypatch.setattr(requests, "get", http_404)

    try:
        svc._api_request("getAlbum", retries=3)
        raised = False
    except requests.exceptions.HTTPError:
        raised = True
    assert raised
    assert len(calls) == 1  # HTTP errors must not be retried


def test_scrobble_is_now_playing_not_a_full_scrobble(monkeypatch):
    svc = make_service()
    captured = {}

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"subsonic-response": {"status": "ok"}}

    def capture(url, params=None, **kwargs):
        captured["params"] = params
        return FakeResponse()

    monkeypatch.setattr(requests, "get", capture)

    ok = svc.scrobble_now_playing("tr-1")

    assert ok is True
    assert captured["params"]["submission"] == "false"  # now-playing, not a played-scrobble
    assert captured["params"]["id"] == "tr-1"