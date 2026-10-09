"""The mpv AO-recovery: a USB DAC pulled mid-play leaves the ALSA output dead
and mpv keeps 'playing' into the dead handle (`snd_pcm_status: No such
device`); only a real teardown cures it — re-setting the audio-device does
NOT (verified live on the Fosi ZD3, 2026-10-09). The backend tracks the
death via mpv's log stream and heals where playback is driven
(play_media/resume/ensure_connected) — the user's own recipe (stop, then
play) made automatic."""
import asyncio
from unittest.mock import MagicMock

import pytest

from app.playback_backends.mpv import MPVService


def _svc(ao_dead=False):
    """MPVService without __init__ — it would spawn a real mpv process."""
    svc = MPVService.__new__(MPVService)
    svc.device_name = "zd3"
    svc.player = MagicMock()
    svc._ao_dead = ao_dead
    svc._playback_active = False
    svc._last_track_finished_at = 0.0
    return svc


# --- the log-observation ---------------------------------------------------------

def test_ao_death_signature_marks_dead():
    svc = _svc()
    svc._observe_ao_health("error", "ao/alsa] snd_pcm_status: No such device")
    assert svc._ao_dead is True


def test_ao_init_failure_signature_marks_dead():
    svc = _svc()
    svc._observe_ao_health("error", "Could not open/initialize audio device")
    assert svc._ao_dead is True


def test_unrelated_error_never_marks():
    svc = _svc()
    svc._observe_ao_health("error", "decode error: bad header")
    assert svc._ao_dead is False


def test_warning_level_never_marks():
    """Only mpv's own errors count — warns are noisy recovery chatter."""
    svc = _svc()
    svc._observe_ao_health("warning", "snd_pcm_status: No such device")
    assert svc._ao_dead is False


# --- the heal --------------------------------------------------------------------

def test_heal_tears_down_and_resets_flag():
    svc = _svc(ao_dead=True)
    svc._playback_active = True
    svc._heal_dead_ao()
    svc.player.command.assert_called_once_with("stop")
    assert svc._playback_active is False   # set BEFORE the stop: no end-file event advances the queue
    assert svc._ao_dead is False


@pytest.mark.asyncio
async def test_play_media_heals_before_loadfile():
    svc = _svc(ao_dead=True)
    svc.get_output_readiness = lambda: {"ready": True, "message": "Target card present: ZD3"}

    ok = await svc.play_media("http://example/tr.mp3", {"title": "t"})

    assert ok is True
    cmds = svc.player.command.call_args_list
    assert any(c.args and c.args[0] == "stop" for c in cmds)   # the heal ran
    assert svc._ao_dead is False
    svc.player.loadfile.assert_called_once_with("http://example/tr.mp3", "replace")


@pytest.mark.asyncio
async def test_play_media_still_refused_when_card_missing():
    svc = _svc()
    svc.get_output_readiness = lambda: {"ready": False, "message": "Target card not present (unplugged?)"}

    ok = await svc.play_media("http://example/tr.mp3")

    assert ok is False
    svc.player.loadfile.assert_not_called()


# --- the resume refusal ----------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_with_dead_ao_refuses_and_heals():
    """The user's failure mode: press play (resume) into a dead output — now
    the backend tears down and REFUSES, so the service stops claiming PLAY."""
    svc = _svc(ao_dead=True)
    result = await svc.resume()
    assert result is False
    svc.player.command.assert_called_once_with("stop")
    assert svc._ao_dead is False


@pytest.mark.asyncio
async def test_resume_normal_passthrough():
    svc = _svc()
    assert await svc.resume() is True
    assert svc.player.pause is False
    svc.player.command.assert_not_called()


# --- ensure_connected (the state pass entry) ---------------------------------------

def test_ensure_connected_heals_first_then_checks_card():
    svc = _svc(ao_dead=True)
    svc.config = MagicMock()
    svc.config.MPV_AUDIO_DEVICE = ""
    svc._bt_checker = MagicMock()
    svc._bt_checker.check_ready = MagicMock(return_value={"ready": True})

    assert svc.ensure_connected() == {"connected": True, "reconnected": False}
    svc.player.command.assert_called_once_with("stop")   # the heal
    svc._bt_checker.check_ready.assert_called_once_with(None)


def test_ensure_connected_reports_missing_card():
    svc = _svc()
    svc.config = MagicMock()
    svc.config.MPV_AUDIO_DEVICE = "alsa/hw:CARD=ZD3,DEV=0"
    svc._bt_checker = MagicMock()
    svc._bt_checker.check_ready = MagicMock(return_value={"ready": False})

    assert svc.ensure_connected() == {"connected": False, "reconnected": False}