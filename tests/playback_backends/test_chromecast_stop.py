"""Tests for ChromecastService stop/connect behaviour.

Uses object.__new__ to skip __init__ (which starts background mDNS discovery).
"""
import pytest
from unittest.mock import MagicMock

from app.playback_backends.chromecast import ChromecastService


def make_service(device_name="kitchen"):
    svc = ChromecastService.__new__(ChromecastService)
    svc.device_name = device_name
    svc.cast_uuid = None
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
    """Nothing confirms (media stop AND app quit both fail) → False, logged
    INFO (benign)."""
    svc = make_service()
    svc.cast = MagicMock()
    svc.mc = MagicMock()
    svc.mc.stop = MagicMock(side_effect=TimeoutError("Execution of stop timed out after 10.0 s."))
    svc.cast.quit_app = MagicMock(side_effect=TimeoutError("quit did not confirm"))
    monkeypatch.setattr("asyncio.to_thread", lambda fn, *a, **k: _async_call(fn, a))
    assert await svc.stop() is False


@pytest.mark.asyncio
async def test_stop_quits_the_receiver_app(monkeypatch):
    """stop = media stop + receiver-app teardown: nothing lingers to be
    resurrected by a later cast (the 3-day-old-album via HA bug)."""
    svc = make_service()
    svc.cast = MagicMock()
    svc.mc = MagicMock()
    monkeypatch.setattr("asyncio.to_thread", lambda fn, *a, **k: _async_call(fn, a))

    assert await svc.stop() is True

    svc.mc.stop.assert_called_once()
    svc.cast.quit_app.assert_called_once()


@pytest.mark.asyncio
async def test_stop_app_quit_alone_confirms(monkeypatch):
    """mc.stop misbehaves but the app quit lands — the device IS stopped
    (the receiver app is gone along with its media): True."""
    svc = make_service()
    svc.cast = MagicMock()
    svc.mc = MagicMock()
    svc.mc.stop = MagicMock(side_effect=TimeoutError("Execution of stop timed out after 10.0 s."))
    monkeypatch.setattr("asyncio.to_thread", lambda fn, *a, **k: _async_call(fn, a))

    assert await svc.stop() is True
    svc.cast.quit_app.assert_called_once()


async def _async_call(fn, args):
    return fn(*args)


def test_connect_tries_only_the_target_device(monkeypatch):
    """No fallback by design: connect the requested speaker or fail loudly."""
    svc = make_service("kitchen")

    tried = []
    monkeypatch.setattr(svc, "_discover_chromecasts",
                        lambda timeout=None, target_name=None, target_uuid=None:
                        tried.append((target_name, target_uuid)) or ([], None, {}))

    connect_calls = []
    import app.playback_backends.chromecast as cc
    monkeypatch.setattr(cc.pychromecast, "get_chromecast_from_cast_info",
                        lambda *a, **k: connect_calls.append(1))

    ok = svc.connect(device_name="kitchen")

    assert ok is False
    assert tried == [("Kitchen", None)]  # only the target, never another room
    assert connect_calls == []   # never attempted a connection