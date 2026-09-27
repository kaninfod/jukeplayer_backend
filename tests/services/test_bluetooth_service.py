"""Tests for the BluetoothService facade over the BlueZ D-Bus layer.

The facade contract (same shapes as the bluetoothctl era) is what the
connect card, device cards, /api/bluetooth routes, and the watchdog
consume — these tests lock it with a fake dbus layer (no real BlueZ).
"""
import pytest
from unittest.mock import MagicMock

from dbus_fast import Variant

from app.services.bluetooth_dbus import BlueZDbus
from app.services.bluetooth_service import (
    BluetoothService,
    is_audio_device,
    mac_from_sink_id,
    pulse_sink_for_mac,
)

BOOM_MAC = "10:94:97:0F:CB:BF"
BOOM_UUIDS = ["0000110b-0000-1000-8000-00805f9b34fb"]


# --- helpers -------------------------------------------------------------------

def make_service(fake_dbus):
    svc = BluetoothService.__new__(BluetoothService)
    svc._dbus = fake_dbus
    svc._watchdog_state = {}
    return svc


class FakeBlueZDbus:
    """Sync stand-in for the async BlueZDbus: the facade's bridge runs the
    closures directly, so plain callables are enough here."""

    def __init__(self, devices=None, battery=None, fail_pair=False):
        self._devices = devices or []
        self._battery = battery
        self._fail_pair = fail_pair
        self.discovery_started = False
        self.discovery_stopped = False
        self.connect_calls = []

    def call(self, fn, timeout=30.0):
        return fn()

    # async API (sync fakes — the closures just call these)
    def status(self):
        return {"powered": True, "controller": "AA:BB:CC:DD:EE:FF"}

    def devices(self):
        return list(self._devices)

    def device_info(self, mac):
        for d in self._devices:
            if d["mac"] == mac.strip().upper():
                return dict(d)
        return {"mac": mac.strip().upper(), "paired": False, "bonded": False,
                "trusted": False, "connected": False, "name": "", "a2dp_sink": False,
                "class": None, "icon": "", "uuids": [], "audio": False}

    def scan_window(self, seconds):
        self.discovery_started = True
        self.discovery_stopped = True
        return list(self._devices)

    def pair_and_connect(self, mac):
        if self._fail_pair:
            return {"mac": mac, "paired": False, "trusted": False, "connected": False,
                    "error": "Pairing rejected by the device"}
        return {"mac": mac, "paired": True, "trusted": True, "connected": True,
                "error": None}

    def connect(self, mac):
        target = mac.strip().upper()
        for d in self._devices:
            if d["mac"] == target:
                d["connected"] = True
                return {"mac": mac, "connected": True, "paired": d["paired"], "error": None}
        return {"mac": mac, "connected": False, "paired": False,
                "error": "Device not known to BlueZ"}

    def disconnect(self, mac):
        return {"mac": mac, "connected": False}

    def forget(self, mac):
        return {"mac": mac, "removed": True}

    def battery(self, mac):
        return self._battery


def boom_device(**overrides):
    device = {"mac": BOOM_MAC, "name": "BOOM 3", "paired": True, "bonded": True,
              "trusted": True, "connected": False, "uuids": list(BOOM_UUIDS),
              "a2dp_sink": True, "class": 0x240404, "icon": "audio-card",
              "audio": True}
    device.update(overrides)
    return device


# --- device dicts from D-Bus properties ------------------------------------------

def test_device_from_ifaces_unwraps_variants():
    """BlueZ properties arrive Variant-wrapped; the device dict must match the
    old info() shape exactly."""
    ifaces = {"org.bluez.Device1": {
        "Address": Variant("s", BOOM_MAC),
        "Alias": Variant("s", "BOOM 3"),
        "Paired": Variant("b", True),
        "Bonded": Variant("b", True),
        "Trusted": Variant("b", True),
        "Connected": Variant("b", False),
        "UUIDs": Variant("as", BOOM_UUIDS),
        "Icon": Variant("s", "audio-card"),
        "Class": Variant("u", 0x240404),
    }}
    device = BlueZDbus._device_from_ifaces("/org/bluez/hci0/dev_X", ifaces)

    assert device["mac"] == BOOM_MAC
    assert device["name"] == "BOOM 3"
    assert device["paired"] is True and device["bonded"] is True
    assert device["trusted"] is True and device["connected"] is False
    assert device["a2dp_sink"] is True
    assert device["audio"] is True
    # exact contract: the old info() keys
    assert set(device.keys()) == {"mac", "name", "paired", "bonded", "trusted",
                                  "connected", "uuids", "a2dp_sink", "class",
                                  "icon", "audio"}


def test_is_audio_device_by_icon_and_class():
    assert is_audio_device({"icon": "audio-card"})
    assert is_audio_device({"icon": "", "class": 0x240404})
    assert not is_audio_device({"icon": "phone", "class": 0x7a020c})
    assert not is_audio_device({"icon": "", "class": None})


# --- facade: lifecycle -------------------------------------------------------------

def test_devices_shape(initialized_fake=None):
    fake = FakeBlueZDbus(devices=[boom_device()])
    service = make_service(fake)
    devices = service.devices()
    assert len(devices) == 1
    assert devices[0]["mac"] == BOOM_MAC
    assert devices[0]["paired"] is True
    assert devices[0]["a2dp_sink"] is True


def test_scan_runs_discovery_window():
    fake = FakeBlueZDbus(devices=[boom_device()])
    service = make_service(fake)
    result = service.scan(seconds=0.01)
    assert fake.discovery_started and fake.discovery_stopped
    assert result[0]["mac"] == BOOM_MAC


def test_pair_and_connect_success():
    fake = FakeBlueZDbus(devices=[boom_device(connected=True, paired=True,
                                                bonded=True, trusted=True)])
    service = make_service(fake)
    result = service.pair_and_connect(BOOM_MAC)
    assert result["paired"] is True
    assert result["trusted"] is True
    assert result["connected"] is True
    assert result["error"] is None


def test_pair_failure_reports_error():
    fake = FakeBlueZDbus()
    fake._fail_pair = True
    service = make_service(fake)
    result = service.pair_and_connect("AA:BB:CC:DD:EE:FF")
    assert result["paired"] is False
    assert "Pairing rejected" in result["error"]


def test_connect_reports_state():
    fake = FakeBlueZDbus(devices=[boom_device(connected=True)])
    service = make_service(fake)
    result = service.connect(BOOM_MAC)
    assert result["connected"] is True and result["error"] is None


def test_connect_unknown_device_fails_cleanly():
    fake = FakeBlueZDbus()
    service = make_service(fake)
    result = service.connect(BOOM_MAC)
    assert result["connected"] is False
    assert "not known" in result["error"]


def test_forget_reports_removed():
    fake = FakeBlueZDbus(devices=[boom_device()])
    service = make_service(fake)
    assert service.forget(BOOM_MAC)["removed"] is True


# --- battery (fe61 misreport filter survives the port) ------------------------------

def test_battery_reads_clear_value():
    fake = FakeBlueZDbus(devices=[boom_device()], battery=70)
    service = make_service(fake)
    assert service.battery_percent(BOOM_MAC, uuids=[]) == 70


def test_battery_fe61_misreport_is_suppressed():
    fake = FakeBlueZDbus(devices=[boom_device()], battery=1)
    service = make_service(fake)
    assert service.battery_percent(BOOM_MAC,
                                   uuids=["0000fe61-0000-1000-8000-00805f9b34fb"]) is None
    # a device WITHOUT the fe61 vendor uuid keeps its low reading
    assert service.battery_percent(BOOM_MAC, uuids=BOOM_UUIDS) == 1


def test_battery_none_when_no_battery_interface():
    fake = FakeBlueZDbus(devices=[boom_device()], battery=None)
    service = make_service(fake)
    assert service.battery_percent(BOOM_MAC, uuids=BOOM_UUIDS) is None


# --- pulse layer (pactl) -------------------------------------------------------------

def test_pulse_sink_for_mac_and_inverse():
    sinks = [{"name": "bluez_sink.10_94_97_0F_CB_BF.a2dp_sink"}]
    assert pulse_sink_for_mac(sinks, BOOM_MAC) == "pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink"
    assert mac_from_sink_id("pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink") == BOOM_MAC
    assert mac_from_sink_id("alsa_output.pci-0000_00_1f.3.analog-stereo") is None
    assert pulse_sink_for_mac(sinks, "AA:BB:CC:DD:EE:FF") is None


def test_sink_for_device_via_pactl(monkeypatch):
    fake = FakeBlueZDbus()
    service = make_service(fake)
    monkeypatch.setattr(BluetoothService, "_pactl",
                        staticmethod(lambda timeout=10.0:
                                     "1\tbluez_sink.10_94_97_0F_CB_BF.a2dp_sink\tmodule\t"
                                     "s16le 2ch 44100Hz\tSUSPENDED"))
    assert service.sink_for_device(BOOM_MAC) == "pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink"
    assert service.sink_for_device("AA:BB:CC:DD:EE:FF") is None


# --- startup reconnect ----------------------------------------------------------------

# --- the real dbus client (no connection — pure helpers) --------------------------------

def test_device_path_uses_adapter():
    fake_dbus = BlueZDbus.__new__(BlueZDbus)
    fake_dbus._adapter_path = "/org/bluez/hci1"
    assert fake_dbus._device_path(BOOM_MAC) == "/org/bluez/hci1/dev_10_94_97_0F_CB_BF"


def test_bridge_exists_and_surfaces_connect_failure():
    """Regression: the real client shipped without the sync `call` bridge —
    the fake satisfied the facade tests while every real call raised
    AttributeError ('BlueZDbus' object has no attribute 'call') and no
    client could pair, scan or toggle. The bridge must exist and surface
    connect failures as RuntimeError (no system BlueZ on this machine)."""
    import asyncio

    client = BlueZDbus()
    with pytest.raises(RuntimeError, match="D-Bus|BlueZ"):
        client.call(lambda: asyncio.sleep(0), timeout=2.0)


def test_call_refuses_to_post_into_a_dead_loop():
    """Regression (hardware, second round): a connect failure that happens
    AFTER the bus connects (e.g. agent registration) used to leave the bus
    set while the loop never ran — calls posted into a dead loop and every
    BT action timed out after its bridge timeout. The bridge must refuse
    when the loop is not running."""
    import asyncio

    client = BlueZDbus()
    client._started.set()
    client._bus = object()      # bus looks connected
    client._connect_error = None
    client._loop = None         # ...but the loop never ran
    with pytest.raises(RuntimeError, match="loop is not running"):
        client.call(lambda: asyncio.sleep(0), timeout=1.0)