"""Tests for the mpv output-readiness checker (Phase C audio targeting)."""
import subprocess

from app.playback_backends.bluetooth import BluetoothAudioChecker

PACTL_OUT = ("0\talsa_output.platform-3f00b840.mailbox.stereo-fallback\tmodule-alsa-card.c\ts16le 2ch 44100Hz\tSUSPENDED\n"
             "1\tbluez_sink.10_94_97_0F_CB_BF.a2dp_sink\tmodule-bluez5-device.c\ts16le 2ch 44100Hz\tSUSPENDED")


def make_checker(monkeypatch, stdout=PACTL_OUT):
    checker = BluetoothAudioChecker()
    monkeypatch.setattr(
        BluetoothAudioChecker, "_run_command",
        staticmethod(lambda command: subprocess.CompletedProcess(
            args=command, returncode=0, stdout=stdout, stderr=""))
    )
    return checker


def test_no_audio_device_override_is_ready():
    checker = BluetoothAudioChecker()
    readiness = checker.check_ready(None)
    assert readiness["ready"] is True


def test_targeted_bt_sink_present_is_ready(monkeypatch):
    checker = make_checker(monkeypatch)
    readiness = checker.check_ready("pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink")
    assert readiness["ready"] is True
    assert readiness["sink_is_bluetooth"] is True
    assert readiness["sink"] == "bluez_sink.10_94_97_0F_CB_BF.a2dp_sink"


def test_targeted_bt_sink_missing_is_not_ready(monkeypatch):
    checker = make_checker(monkeypatch)
    readiness = checker.check_ready("pulse/bluez_sink.A8_F5_E1_7E_08_17.a2dp_sink")
    assert readiness["ready"] is False
    assert "not present" in readiness["message"]


def test_pactl_failure_does_not_block_playback(monkeypatch):
    checker = BluetoothAudioChecker()
    monkeypatch.setattr(
        BluetoothAudioChecker, "_run_command",
        staticmethod(lambda command: subprocess.CompletedProcess(
            args=command, returncode=1, stdout="", stderr="pactl exploded"))
    )
    readiness = checker.check_ready("pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink")
    assert readiness["ready"] is True