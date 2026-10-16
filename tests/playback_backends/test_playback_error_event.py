"""PLAYBACK_ERROR: the dedicated signal for "a playback died/failed because
the output was not ready" (2026-10-10 session agreement — raised only for
now: no listening handler, no client notice yet). The user-visible bit of
this round is the QUEUE HOLD: mpv end-file reason=error must never advance
the album like a normal track-end."""
from unittest.mock import MagicMock

import pytest

from app.core import event_bus
from app.core.event_factory import EventType
from app.playback_backends.mpv import MPVService


def _svc():
    """MPVService without __init__ — it would spawn a real mpv process."""
    svc = MPVService.__new__(MPVService)
    svc.device_name = "zd3"
    svc.player = MagicMock()
    svc._ao_dead = False
    svc._playback_active = False
    svc._last_track_finished_at = 0.0
    return svc


def test_end_file_error_holds_queue_and_raises_playback_error(monkeypatch):
    emitted = []
    monkeypatch.setattr(event_bus, "emit", lambda ev: emitted.append(ev))

    _svc()._handle_end_file({"reason": "error", "file_error": "No such device"})

    assert [ev.type for ev in emitted] == [EventType.PLAYBACK_ERROR]
    payload = emitted[0].payload
    assert payload["device_name"] == "zd3"
    assert payload["source"] == "output_died"
    assert payload["error"] == "No such device"


def test_end_file_eof_still_advances(monkeypatch):
    """Regression: a real track end keeps the existing TRACK_FINISHED flow."""
    emitted = []
    monkeypatch.setattr(event_bus, "emit", lambda ev: emitted.append(ev))

    _svc()._handle_end_file({"reason": "eof"})

    assert [ev.type for ev in emitted] == [EventType.TRACK_FINISHED]


def test_playback_error_event_value():
    """The event name on the wire, pinned for the later listening handler."""
    assert EventType.PLAYBACK_ERROR.value == "playback_error"


def test_playback_error_respects_the_event_debounce(monkeypatch):
    """Two end-file events inside one second emit once (same discipline as
    TRACK_FINISHED — error storms from a flapping device must not flood)."""
    emitted = []
    monkeypatch.setattr(event_bus, "emit", lambda ev: emitted.append(ev))
    svc = _svc()

    svc._handle_end_file({"reason": "error"})
    svc._handle_end_file({"reason": "error"})

    assert len(emitted) == 1