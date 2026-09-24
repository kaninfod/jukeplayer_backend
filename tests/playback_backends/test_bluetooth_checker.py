"""Tests for the mpv output-readiness checker (Phase C audio targeting)."""
import pytest

from app.services.bluetooth_service import BluetoothAudioChecker


def make_checker(monkeypatch, sinks):
    checker = BluetoothAudioChecker()
    monkeypatch.setattr(BluetoothAudioChecker, "_list_sinks", lambda self: list(sinks))
    return checker


def test_no_audio_device_override_is_ready():
    checker = BluetoothAudioChecker()
    readiness = checker.check_ready(None)
    assert readiness["ready"] is True


def test_targeted_bt_sink_present_is_ready(monkeypatch):
    checker = make_checker(monkeypatch, [
        "alsa_output.platform-3f00b840.mailbox.stereo-fallback",
        "bluez_sink.10_94_97_0F_CB_BF.a2dp_sink",
    ])
    readiness = checker.check_ready("pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink")
    assert readiness["ready"] is True
    assert readiness["sink_is_bluetooth"] is True
    assert readiness["sink"] == "bluez_sink.10_94_97_0F_CB_BF.a2dp_sink"


def test_targeted_bt_sink_missing_is_not_ready(monkeypatch):
    checker = make_checker(monkeypatch, [
        "alsa_output.platform-3f00b840.mailbox.stereo-fallback",
        "bluez_sink.10_94_97_0F_CB_BF.a2dp_sink",
    ])
    readiness = checker.check_ready("pulse/bluez_sink.A8_F5_E1_7E_08_17.a2dp_sink")
    assert readiness["ready"] is False
    assert "not present" in readiness["message"]


def test_pactl_failure_does_not_block_playback(monkeypatch):
    checker = BluetoothAudioChecker()

    def broken(self):
        raise RuntimeError("pactl unavailable")

    monkeypatch.setattr(BluetoothAudioChecker, "_list_sinks", broken)
    readiness = checker.check_ready("pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink")
    assert readiness["ready"] is True
    assert "letting mpv try" in readiness["message"]