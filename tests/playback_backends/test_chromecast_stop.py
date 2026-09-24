"""Tests for ChromecastService stop/connect behaviour.

Uses object.__new__ to skip __init__ (which starts background mDNS discovery).
"""
import pytest
from unittest.mock import MagicMock

from app.playback_backends.chromecast import ChromecastService


def make_service(device_name="kitchen"):
    svc = ChromecastService.__new__(ChromecastService)
    svc.device_name = device_name
    svc.cast = None
    svc.mc = None
    svc.status_listener = None
    return svc


@pytest.mark.asyncio
async def test_stop_without_connection_is_success():
    """A missing connection means nothing is playing — stop must succeed
    WITHOUT attempting a reconnect (root cause of the stop-timeout spam)."""
    svc = make_service()
    # No ensure_connected call possible: it would try a real connect()
    assert await svc.stop() is True


@pytest.mark.asyncio
async def test_stop_timeout_is_benign(monkeypatch):
    svc = make_service()
    svc.cast = MagicMock()
    svc.mc = MagicMock()
    svc.mc.stop = MagicMock(side_effect=TimeoutError("Execution of stop timed out after 10.0 s."))
    monkeypatch.setattr("asyncio.to_thread", lambda fn, *a, **k: _async_call(fn, a))
    assert await svc.stop() is False  # returns False, but logged as INFO (benign)


async def _async_call(fn, args):
    return fn(*args)


def test_connect_without_fallback_never_expands_device_list(monkeypatch):
    """fallback=False (new default) must not try other rooms silently."""
    svc = make_service("kitchen")

    tried = []
    monkeypatch.setattr(svc, "_discover_chromecasts",
                        lambda timeout=None, target_name=None: tried.append(target_name) or ([], None, {}))

    connect_calls = []
    import app.playback_backends.chromecast as cc
    monkeypatch.setattr(cc.pychromecast, "get_chromecast_from_cast_info",
                        lambda *a, **k: connect_calls.append(1))

    ok = svc.connect(device_name="kitchen", fallback=False)

    assert ok is False
    assert tried == ["Kitchen"]  # only the normalized target, no fallbacks
    assert connect_calls == []       # never attempted a connection


def test_connect_explicit_fallback_still_available(monkeypatch):
    """fallback=True remains available for explicit callers (e.g. UI-driven)."""
    svc = make_service("kitchen")

    tried = []
    monkeypatch.setattr(svc, "_discover_chromecasts",
                        lambda timeout=None, target_name=None: tried.append(target_name) or ([], None, {}))

    import app.playback_backends.chromecast as cc
    monkeypatch.setattr(cc.pychromecast, "get_chromecast_from_cast_info",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not connect")))

    ok = svc.connect(device_name="kitchen", fallback=True)

    assert ok is False
    # normalized target + configured fallback devices were attempted
    assert tried == ["Kitchen", "Bedroom", "Kitchen"]