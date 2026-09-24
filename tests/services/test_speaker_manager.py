"""Tests for Phase B live speaker management: store helpers, registry
add/remove, broker client re-homing, and the SpeakerManagerService."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.config_store import ConfigService, ConfigStoreService
from app.services.speaker_broker_service import SpeakerBrokerService
from app.services.speaker_manager_service import (
    SpeakerManagerService,
    normalize_speaker_name,
)
from app.services.speakers_service import Speaker, SpeakersService


class FakeVolumeManager:
    def __init__(self):
        self.sync_volume_from_backend = AsyncMock(return_value=50)


class FakePlayer:
    """Minimal MediaPlayerService double: stop + context + volume manager."""

    def __init__(self, name):
        self.device_name = name
        self.stopped = False
        self.volume_manager = FakeVolumeManager()
        self.playback_backend = SimpleNamespace(is_connected=lambda: True, disconnect=MagicMock())
        self.stop = AsyncMock(side_effect=self._mark_stopped)

    async def _mark_stopped(self):
        self.stopped = True

    def get_context(self, minimal=False):
        return {"status": "idle"}


@pytest.fixture
def stack(tmp_path, monkeypatch):
    """Store + config service + speakers registry (stubbed construction) +
    manager, all isolated to a tmp config file."""
    store = ConfigStoreService(path=str(tmp_path / "config.json"))
    system = SimpleNamespace(LOG_SERVER_HOST="", LOG_SERVER_PORT=0)
    config_service = ConfigService(store=store, system_config=system)
    speakers = SpeakersService()

    def fake_build(entry):
        return Speaker(f"id-{entry['name']}", entry["name"], entry.get("backend", "chromecast"),
                       FakePlayer(entry["name"]),
                       display_name=entry.get("display_name", ""))

    monkeypatch.setattr(speakers, "_build_speaker", fake_build)
    broker = SimpleNamespace(handle_speaker_removed=AsyncMock())
    manager = SpeakerManagerService(store=store, config_service=config_service,
                                    speakers_service=speakers, broker=broker)
    return SimpleNamespace(store=store, config=config_service, speakers=speakers,
                           manager=manager, broker=broker)


# --- name normalization -------------------------------------------------------

def test_normalize_speaker_name():
    assert normalize_speaker_name("Living Room") == "living_room"
    assert normalize_speaker_name("  Kitchen  ") == "kitchen"
    assert normalize_speaker_name("Bed\tRoom") == "bed_room"
    assert normalize_speaker_name(None) == ""


# --- add ----------------------------------------------------------------------

def test_add_persists_to_store_and_registers_live(stack):
    entry = stack.manager.add_speaker("Living Room", backend="chromecast", is_default=True)

    assert entry == {"name": "living_room", "backend": "chromecast",
                     "options": {}, "is_default": True, "display_name": ""}
    # persisted (store reloaded from disk)
    reloaded = ConfigStoreService(path=stack.store.path)
    assert reloaded.section("speakers") == [entry]
    # live registry has the speaker
    assert stack.speakers.get_speaker(speaker_name="living_room") is not None
    assert stack.speakers.get_default_speaker().speaker_name == "living_room"


def test_add_duplicate_rejected(stack):
    stack.manager.add_speaker("kitchen")
    with pytest.raises(ValueError, match="already configured"):
        stack.manager.add_speaker("Kitchen")


def test_add_unknown_backend_rejected(stack):
    with pytest.raises(ValueError, match="Unknown backend"):
        stack.manager.add_speaker("den", backend="airplay")


def test_add_default_clears_previous_default(stack):
    stack.manager.add_speaker("a", is_default=True)
    stack.manager.add_speaker("b", is_default=True)

    names = {s["name"]: s["is_default"] for s in stack.store.section("speakers")}
    assert names == {"a": False, "b": True}
    assert stack.speakers.get_default_speaker().speaker_name == "b"


# --- remove -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_updates_store_registry_and_broker(stack):
    stack.manager.add_speaker("kitchen", is_default=True)
    removed_speaker = stack.speakers.get_speaker(speaker_name="kitchen")

    result = await stack.manager.remove_speaker("Kitchen")

    assert result["removed"] == "kitchen"
    assert stack.store.section("speakers") == []
    assert stack.speakers.get_speaker(speaker_name="kitchen") is None
    assert removed_speaker.mediaplayer.stopped is True
    removed_speaker.mediaplayer.playback_backend.disconnect.assert_called_once()
    stack.broker.handle_speaker_removed.assert_awaited_once_with(removed_speaker)


@pytest.mark.asyncio
async def test_remove_default_promotes_first_remaining(stack):
    stack.manager.add_speaker("a", is_default=True)
    stack.manager.add_speaker("b")

    await stack.manager.remove_speaker("a")

    names = {s["name"]: s["is_default"] for s in stack.store.section("speakers")}
    assert names == {"b": True}
    assert stack.config.default_speaker_name() == "b"
    assert stack.speakers.get_default_speaker().speaker_name == "b"


@pytest.mark.asyncio
async def test_remove_unknown_raises_and_touches_nothing(stack):
    with pytest.raises(ValueError, match="not configured"):
        await stack.manager.remove_speaker("nowhere")
    assert stack.store.section("speakers") == []


@pytest.mark.asyncio
async def test_remove_last_speaker_clears_default(stack):
    stack.manager.add_speaker("only", is_default=True)
    await stack.manager.remove_speaker("only")
    assert stack.config.default_speaker_name() is None
    assert stack.speakers.get_default_speaker() is None


# --- default ------------------------------------------------------------------

def test_set_default_updates_store_and_registry(stack):
    stack.manager.add_speaker("a", is_default=True)
    stack.manager.add_speaker("b")

    result = stack.manager.set_default("b")

    assert result["default"] == "b"
    assert all(s["is_default"] == (s["name"] == "b") for s in stack.store.section("speakers"))
    assert stack.speakers.get_default_speaker().speaker_name == "b"


def test_set_default_unknown_rejected(stack):
    stack.manager.add_speaker("a")
    with pytest.raises(ValueError, match="not configured"):
        stack.manager.set_default("ghost")


# --- display names ------------------------------------------------------------

def test_add_with_display_name_persists_and_registers(stack):
    entry = stack.manager.add_speaker("tv_lounge", display_name="TV Lounge Speaker")

    assert entry["display_name"] == "TV Lounge Speaker"
    reloaded = ConfigStoreService(path=stack.store.path)
    assert reloaded.section("speakers")[0]["display_name"] == "TV Lounge Speaker"
    live = stack.speakers.get_speaker(speaker_name="tv_lounge")
    assert live.display_name == "TV Lounge Speaker"
    assert live.to_dict()["display_name"] == "TV Lounge Speaker"


def test_set_display_name_updates_store_and_live(stack):
    stack.manager.add_speaker("living_room")
    stack.manager.set_display_name("living_room", "Living Room Speaker")

    assert stack.store.section("speakers")[0]["display_name"] == "Living Room Speaker"
    assert stack.speakers.get_speaker(speaker_name="living_room").display_name == "Living Room Speaker"

    # empty value clears it (UI falls back to the technical name)
    stack.manager.set_display_name("living_room", "  ")
    assert stack.store.section("speakers")[0]["display_name"] == ""
    assert stack.speakers.get_speaker(speaker_name="living_room").display_name == ""


def test_set_display_name_unknown_rejected(stack):
    stack.manager.add_speaker("a")
    with pytest.raises(ValueError, match="not configured"):
        stack.manager.set_display_name("ghost", "Nope")


# --- discovery ----------------------------------------------------------------

def test_discover_maps_names_and_flags_configured(stack, monkeypatch):
    from app.playback_backends import chromecast as cc

    def fake_discover(timeout=None):  # sync — discover() calls it directly
        return [
            {"name": "Living Room", "model": "Nest Audio", "host": "10.0.0.5", "uuid": "u1"},
            {"name": "kitchen", "model": "Mini", "host": "10.0.0.6", "uuid": "u2"},
            {"name": "", "model": "X", "host": "10.0.0.7", "uuid": "u3"},
        ]

    monkeypatch.setattr(cc, "discover_devices", fake_discover)
    stack.manager.add_speaker("Living Room")

    devices = stack.manager.discover()

    assert [d["store_name"] for d in devices] == ["living_room", "kitchen"]
    assert devices[0]["configured"] is True
    assert devices[1]["configured"] is False
    assert devices[0]["model"] == "Nest Audio"


# --- broker: clients re-homed when a speaker is removed -----------------------

@pytest.mark.asyncio
async def test_broker_rehomes_clients_to_default_on_removal(mock_event_bus):
    speakers = SpeakersService()
    speaker_a = Speaker("id-a", "a", "chromecast", SimpleNamespace(get_context=lambda minimal=False: {}))
    speaker_b = Speaker("id-b", "b", "chromecast", SimpleNamespace(get_context=lambda minimal=False: {}))
    speakers._speakers = {"a": speaker_a, "b": speaker_b}
    speakers.set_default_name("b")
    speaker_a.clients = {"c1", "c2"}

    clients = {
        "c1": SimpleNamespace(client_id="c1", speaker_name="a", capabilities=[],
                              send_callback=AsyncMock()),
        "c2": SimpleNamespace(client_id="c2", speaker_name="a", capabilities=[],
                              send_callback=AsyncMock()),
    }
    broker = SpeakerBrokerService(SimpleNamespace(_clients=clients), speakers, mock_event_bus)

    await broker.handle_speaker_removed(speaker_a)

    assert clients["c1"].speaker_name == "b"
    assert clients["c2"].speaker_name == "b"
    assert speaker_a.clients == set()
    assert speaker_b.clients == {"c1", "c2"}
    clients["c1"].send_callback.assert_awaited_once()
    clients["c2"].send_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_broker_detaches_clients_when_no_speakers_remain(mock_event_bus):
    speakers = SpeakersService()
    speaker_a = Speaker("id-a", "a", "chromecast", SimpleNamespace(get_context=lambda minimal=False: {}))
    speakers._speakers = {"a": speaker_a}
    speakers.set_default_name("a")
    speaker_a.clients = {"c1"}

    client = SimpleNamespace(client_id="c1", speaker_name="a", capabilities=[],
                             send_callback=AsyncMock())
    broker = SpeakerBrokerService(SimpleNamespace(_clients={"c1": client}), speakers, mock_event_bus)

    await broker.handle_speaker_removed(speaker_a)

    assert client.speaker_name is None
    client.send_callback.assert_not_awaited()