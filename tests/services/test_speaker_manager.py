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
        audio_device = (entry.get("options") or {}).get("audio_device") or ""
        backend_name = entry.get("backend", "chromecast")
        from app.services.bluetooth_service import mac_from_sink_id
        bt_mac = mac_from_sink_id(audio_device)
        speaker_type = ("chromecast" if backend_name == "chromecast"
                        else "bluetooth" if bt_mac else "local")
        speaker = Speaker(f"id-{entry['name']}", entry["name"], backend_name,
                          FakePlayer(entry["name"]),
                          display_name=entry.get("display_name", ""),
                          speaker_type=speaker_type)
        speaker.bt_mac = bt_mac
        return speaker

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


@pytest.mark.asyncio
async def test_broker_resolves_display_form_device_names(mock_event_bus):
    """TRACK_FINISHED from an mpv speaker carries the display-form name
    ('OPENRUN PRO 2 BY SHOKZ') — routing must still land on that speaker
    instead of falling back to the default (routing bug 2026-09-24)."""
    from app.services.media_player_service import MediaPlayerService  # noqa: F401

    speakers = SpeakersService()
    headphones = Speaker("id-openrun", "openrun_pro_2_by_shokz", "mpv",
                         SimpleNamespace(get_context=lambda minimal=False: {}))
    default_speaker = Speaker("id-b", "living_room", "chromecast",
                              SimpleNamespace(get_context=lambda minimal=False: {}))
    speakers._speakers = {"openrun_pro_2_by_shokz": headphones, "living_room": default_speaker}
    speakers.set_default_name("living_room")

    broker = SpeakerBrokerService(SimpleNamespace(_clients={}), speakers, mock_event_bus)

    # display-form (uppercase + spaces) and store form both resolve correctly
    assert broker.resolve_speaker(device_name="OPENRUN PRO 2 BY SHOKZ") is headphones
    assert broker.resolve_speaker(device_name="openrun_pro_2_by_shokz") is headphones
    assert broker.resolve_speaker(device_name="Openrun Pro 2 By Shokz") is headphones

# --- state pass (watchdog) ----------------------------------------------------

class StubBTState:
    """BluetoothService double for state-pass tests."""
    def __init__(self, sink_by_mac, paired_by_mac, connect_ok=True):
        self.sink_by_mac = sink_by_mac
        self.paired_by_mac = paired_by_mac
        self.connect_ok = connect_ok
        self.connect_calls = []

    def sink_for_device(self, mac):
        return self.sink_by_mac.get(mac)

    def info(self, mac):
        return {"paired": self.paired_by_mac.get(mac, False), "connected": False,
                "name": mac, "uuids": ["0000110b-0000-1000-8000-00805f9b34fb"]}

    def connect(self, mac):
        self.connect_calls.append(mac)
        return {"mac": mac, "connected": self.connect_ok, "error": None if self.connect_ok else "not reachable"}

    def battery_percent(self, mac, uuids=None):
        return 42

    def forget(self, mac):
        pass


def state_manager(stack, monkeypatch, bt_stub, discovered=None):
    """Manager with a stubbed bluetooth service + patched CC discovery."""
    from app.services.speaker_manager_service import SpeakerManagerService
    from app.playback_backends import chromecast as cc
    monkeypatch.setattr(cc, "discovered_names",
                        lambda: discovered if discovered is not None else set())
    return SpeakerManagerService(
        store=stack.store, config_service=stack.config,
        speakers_service=stack.speakers, broker=stack.broker,
        bluetooth_service=bt_stub)


BOOM_BT = {"name": "boom_3",
           "options": {"audio_device": "pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink"}}


def test_state_pass_reconnects_lost_bt_speaker(stack, monkeypatch):
    stack.manager.add_speaker("boom_3", backend="mpv",
                              options={"audio_device": "pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink"})
    bt = StubBTState({"10:94:97:0F:CB:BF": None},  # sink gone
                     {"10:94:97:0F:CB:BF": True}, connect_ok=True)
    manager = state_manager(stack, monkeypatch, bt)
    result = manager.update_speaker_states()
    assert bt.connect_calls == ["10:94:97:0F:CB:BF"]
    assert result["reconnected"] == ["boom_3"]
    speaker = stack.speakers.get_speaker(speaker_name="boom_3")
    assert speaker.connected is True
    assert speaker.available is True
    assert speaker.battery == 42


def test_state_pass_skips_connected_bt_speaker(stack, monkeypatch):
    stack.manager.add_speaker("boom_3", backend="mpv",
                              options={"audio_device": "pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink"})
    bt = StubBTState({"10:94:97:0F:CB:BF": "pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink"},
                     {"10:94:97:0F:CB:BF": True}, connect_ok=True)
    manager = state_manager(stack, monkeypatch, bt)
    manager.update_speaker_states()
    assert bt.connect_calls == []
    speaker = stack.speakers.get_speaker(speaker_name="boom_3")
    assert speaker.connected is True
    assert speaker.available is True


def test_state_pass_backs_off_after_failures(stack, monkeypatch):
    stack.manager.add_speaker("boom_3", backend="mpv",
                              options={"audio_device": "pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink"})
    bt = StubBTState({"10:94:97:0F:CB:BF": None}, {"10:94:97:0F:CB:BF": True}, connect_ok=False)
    manager = state_manager(stack, monkeypatch, bt)
    manager.update_speaker_states()
    assert bt.connect_calls == ["10:94:97:0F:CB:BF"]
    manager.update_speaker_states()
    assert bt.connect_calls == ["10:94:97:0F:CB:BF"]      # backoff: no second attempt
    bt._reconnect_hint = True
    manager._reconnect_state["10:94:97:0F:CB:BF"]["not_before"] = 0
    manager.update_speaker_states()
    assert len(bt.connect_calls) == 2


def test_state_pass_marks_cc_available(stack, monkeypatch):
    stack.manager.add_speaker("Living Room", backend="chromecast", display_name="Living Room Speaker")
    store_name = stack.store.section("speakers")[0]["name"]
    bt = StubBTState({}, {}, connect_ok=True)
    manager = state_manager(stack, monkeypatch, bt, discovered={"Living Room"})
    manager.update_speaker_states()
    speaker = stack.speakers.get_speaker(speaker_name=store_name)
    assert speaker.type == "chromecast"
    assert speaker.available is True          # discovered on the network
    assert speaker.connected is True          # fixture backend reports connected


def entry_name():
    return "living_room_speaker"