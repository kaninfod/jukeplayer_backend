"""Tests for the BluetoothService (Phase C): parsers + command flows with
stubbed subprocess output."""
from app.services.bluetooth_service import (
    BluetoothService,
    is_audio_device,
    mac_from_sink_id,
    mac_to_underscored,
    parse_devices,
    parse_info,
    parse_pactl_sinks,
    parse_scan_attributes,
    pulse_sink_for_mac,
)

def test_mac_from_sink_id():
    assert mac_from_sink_id("pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink") == "10:94:97:0F:CB:BF"
    assert mac_from_sink_id("pulse/alsa_output.stereo") is None
    assert mac_from_sink_id(None) is None
    assert mac_from_sink_id("") is None

# --- parsers -----------------------------------------------------------------

def test_parse_devices_dedupes_and_uppercases():
    output = """[NEW] Device 10:94:97:0f:cb:bf BOOM 3
[CHG] Device 10:94:97:0f:cb:bf Alias: BOOM 3
Device 78:BD:BC:E0:55:D1 [TV] UE32J6275
Device 10:94:97:0F:CB:BF BOOM 3"""
    devices = parse_devices(output)
    assert devices == [
        {"mac": "10:94:97:0F:CB:BF", "name": "BOOM 3"},
        {"mac": "78:BD:BC:E0:55:D1", "name": "[TV] UE32J6275"},
    ]


def test_parse_info_flags_and_a2dp_uuid():
    output = """Device 10:94:97:0F:CB:BF (public)
        Name: BOOM 3
        Alias: BOOM 3
        Paired: yes
        Trusted: yes
        Connected: no
        UUID: Audio Sink                (0000110b-0000-1000-8000-00805f9b34fb)
        UUID: A/V Remote Control Target (0000110c-0000-1000-8000-00805f9b34fb)"""
    info = parse_info(output)
    assert info["name"] == "BOOM 3"
    assert info["paired"] is True
    assert info["trusted"] is True
    assert info["connected"] is False
    assert info["a2dp_sink"] is True


def test_parse_info_defaults():
    info = parse_info("Device AA:BB:CC:DD:EE:FF")
    assert info == {"paired": False, "trusted": False, "connected": False,
                    "name": "", "a2dp_sink": False, "class": None, "icon": "",
                    "audio": False, "uuids": []}


def test_parse_info_class_icon_audio():
    output = """Device 10:94:97:0F:CB:BF (public)
        Name: BOOM 3
        Class: 0x00240414 (2360340)
        Icon: audio-card
        Paired: yes"""
    info = parse_info(output)
    assert info["class"] == 0x240414
    assert info["icon"] == "audio-card"
    assert info["audio"] is True


def test_is_audio_device():
    # audio icon → audio
    assert is_audio_device({"icon": "audio-card"}) is True
    # CoD major class 4 (audio/video) → audio
    assert is_audio_device({"class": 0x240414}) is True
    assert is_audio_device({"class": 0x000204}) is False  # major 2 = phone
    # unknown class/icon → not audio (may still be shown if named)
    assert is_audio_device({}) is False


def test_parse_scan_attributes_class_and_icon():
    text = """[CHG] Device 10:94:97:0F:CB:BF Class: 0x00240414 (2360340)
[CHG] Device 10:94:97:0F:CB:BF Icon: audio-card
[NEW] Device 78:98:68:00:00:00 78-98-68-00-00-00
[CHG] Device 78:98:68:00:00:00 RSSI: -80"""
    attrs = parse_scan_attributes(text)
    assert attrs["10:94:97:0F:CB:BF"] == {"class": 0x240414, "icon": "audio-card"}
    assert attrs["78:98:68:00:00:00"] == {"class": None, "icon": ""}


def test_parse_pactl_sinks():
    output = ("0\talsa_output.platform-3f00b840.mailbox.stereo-fallback\tmodule-alsa-card.c\ts16le 2ch 44100Hz\tSUSPENDED\n"
              "1\tbluez_sink.10_94_97_0F_CB_BF.a2dp_sink\tmodule-bluez5-device.c\ts16le 2ch 44100Hz\tSUSPENDED")
    sinks = parse_pactl_sinks(output)
    assert sinks[1]["name"] == "bluez_sink.10_94_97_0F_CB_BF.a2dp_sink"
    assert sinks[1]["state"] == "SUSPENDED"


def test_pulse_sink_for_mac():
    sinks = [{"index": "1", "name": "bluez_sink.10_94_97_0F_CB_BF.a2dp_sink", "state": "SUSPENDED"}]
    assert pulse_sink_for_mac(sinks, "10:94:97:0F:CB:BF") == "pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink"
    assert pulse_sink_for_mac(sinks, "AA:BB:CC:DD:EE:FF") is None
    assert mac_to_underscored("10:94:97:0f:cb:bf") == "10_94_97_0F_CB_BF"


# --- service flows (subprocess stubbed) --------------------------------------

def make_service(monkeypatch, outputs):
    """BluetoothService with canned _run/_ctl outputs by command tuple."""
    service = BluetoothService()

    def fake_run(*args, timeout=15.0):
        return outputs.get(args, "")

    monkeypatch.setattr(BluetoothService, "_run", staticmethod(fake_run))
    return service


def test_devices_parses_flags(monkeypatch):
    outputs = {
        ("bluetoothctl", "devices"): "Device 10:94:97:0F:CB:BF BOOM 3",
        ("bluetoothctl", "info", "10:94:97:0F:CB:BF"): "Name: BOOM 3\nPaired: yes\nTrusted: yes\nConnected: no\nUUID: Audio Sink (0000110b-0000-1000-8000-00805f9b34fb)",
    }
    service = make_service(monkeypatch, outputs)
    devices = service.devices()
    assert len(devices) == 1
    device = devices[0]
    assert device["mac"] == "10:94:97:0F:CB:BF"
    assert device["name"] == "BOOM 3"
    assert device["paired"] is True
    assert device["trusted"] is True
    assert device["connected"] is False
    assert device["a2dp_sink"] is True


def test_pair_and_connect_success(monkeypatch):
    outputs = {
        ("bluetoothctl", "pair", "10:94:97:0F:CB:BF"): "Attempting to pair with 10:94:97:0F:CB:BF\nPairing successful",
        ("bluetoothctl", "trust", "10:94:97:0F:CB:BF"): "Changing 10:94:97:0F:CB:BF trust succeeded",
        ("bluetoothctl", "connect", "10:94:97:0F:CB:BF"): "Connection successful",
        ("bluetoothctl", "info", "10:94:97:0F:CB:BF"): "Name: BOOM 3\nPaired: yes\nTrusted: yes\nConnected: yes\nUUID: Audio Sink (0000110b-0000-1000-8000-00805f9b34fb)",
    }
    service = make_service(monkeypatch, outputs)
    result = service.pair_and_connect("10:94:97:0F:CB:BF")
    assert result["paired"] is True
    assert result["trusted"] is True
    assert result["connected"] is True
    assert result["error"] is None


def test_pair_failure_reports_error(monkeypatch):
    outputs = {
        ("bluetoothctl", "pair", "AA:BB:CC:DD:EE:FF"): "Failed to pair: org.bluez.Error.AuthenticationRejected",
        ("bluetoothctl", "info", "AA:BB:CC:DD:EE:FF"): "Name: X\nPaired: no",
    }
    service = make_service(monkeypatch, outputs)
    result = service.pair_and_connect("AA:BB:CC:DD:EE:FF")
    assert result["paired"] is False
    assert "Failed to pair" in result["error"]


def test_sink_for_device(monkeypatch):
    outputs = {
        ("pactl", "list", "sinks", "short"):
            "1\tbluez_sink.10_94_97_0F_CB_BF.a2dp_sink\tmodule-bluez5-device.c\ts16le 2ch 44100Hz\tSUSPENDED",
    }
    service = make_service(monkeypatch, outputs)
    assert service.sink_for_device("10:94:97:0F:CB:BF") == "pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink"
    assert service.sink_for_device("AA:BB:CC:DD:EE:FF") is None


def test_auto_connect_skips_unpaired(monkeypatch):
    """Only paired-but-disconnected A2DP devices get a connect attempt."""
    calls = []
    outputs = {
        ("bluetoothctl", "devices"): "Device 10:94:97:0F:CB:BF BOOM 3",
        ("bluetoothctl", "info", "10:94:97:0F:CB:BF"): "Name: BOOM 3\nPaired: yes\nConnected: no\nUUID: Audio Sink (0000110b-0000-1000-8000-00805f9b34fb)",
    }
    service = make_service(monkeypatch, outputs)
    monkeypatch.setattr(BluetoothService, "connect",
                        lambda self, mac: calls.append(mac) or {"connected": True})
    service.auto_connect_trusted()
    assert calls == ["10:94:97:0F:CB:BF"]