"""Tests for volume state handling: cast-status propagation, read-only sync."""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.core import EventType, Event
from app.core.event_bus import EventBus
from app.core.event_bus import event_bus as bus_singleton
from app.playback_backends.chromecast import ChromecastMediaStatusListener
from app.services.media_player_service.volume_manager import VolumeManager


def make_status(volume_level=0.33, volume_muted=False, session_id="s1"):
    return SimpleNamespace(
        display_name="Default Media Receiver",
        app_id="CC1AD845",
        session_id=session_id,
        volume_level=volume_level,
        volume_muted=volume_muted,
    )


def test_cast_status_volume_change_emits_event(monkeypatch):
    listener = ChromecastMediaStatusListener("kitchen")
    emitted = []
    monkeypatch.setattr(bus_singleton, "emit",
                        lambda event: emitted.append(event))

    listener.new_cast_status(make_status(volume_level=0.33))

    assert len(emitted) == 1
    assert emitted[0].type == EventType.VOLUME_CHANGED
    assert emitted[0].payload == {"device_name": "kitchen", "volume": 33, "muted": False}


def test_cast_status_same_volume_does_not_re_emit(monkeypatch):
    listener = ChromecastMediaStatusListener("kitchen")
    emitted = []
    monkeypatch.setattr(bus_singleton, "emit",
                        lambda event: emitted.append(event))

    listener.new_cast_status(make_status(volume_level=0.33))
    listener.new_cast_status(make_status(volume_level=0.33))

    assert len(emitted) == 1  # only the first status emits


def test_cast_status_mute_toggle_emits_again(monkeypatch):
    listener = ChromecastMediaStatusListener("kitchen")
    emitted = []
    monkeypatch.setattr(bus_singleton, "emit",
                        lambda event: emitted.append(event))

    listener.new_cast_status(make_status(volume_level=0.33, volume_muted=False))
    listener.new_cast_status(make_status(volume_level=0.33, volume_muted=True))

    assert len(emitted) == 2
    assert emitted[1].payload["muted"] is True


@pytest.mark.asyncio
async def test_sync_volume_from_backend_is_read_only():
    """sync must pull the device volume into state WITHOUT writing it back
    (the old write-back caused the volume ping-pong)."""
    backend = MagicMock()
    backend.get_volume = AsyncMock(return_value=0.33)
    backend.set_volume = AsyncMock()

    vm = VolumeManager(backend)
    vm._volume = 50

    result = await vm.sync_volume_from_backend()

    assert result == 33
    assert vm.volume == 33
    backend.set_volume.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_volume_from_backend_handles_none():
    backend = MagicMock()
    backend.get_volume = AsyncMock(return_value=None)

    vm = VolumeManager(backend)
    vm._volume = 50

    result = await vm.sync_volume_from_backend()

    assert result == 50  # unchanged when backend reports nothing


def test_set_local_volume_clamps():
    vm = VolumeManager(MagicMock())
    assert vm.set_local_volume(133) == 100
    assert vm.set_local_volume(-5) == 0
    assert vm.set_local_volume(42.6) == 43
    assert vm.set_local_volume(None) == 43  # unchanged
    vm.set_local_volume(50, muted=True)
    assert vm.is_muted is True