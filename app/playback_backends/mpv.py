from __future__ import annotations

import logging
import os
from typing import Dict, Optional

# The user-requested library
import python_mpv_jsonipc as mpv

from app.config import config
from app.playback_backends.base import PlaybackBackend
from app.services.bluetooth_service import BluetoothAudioChecker
from app.services.sound_profile import compile_snd_profile, compose_profiles

logger = logging.getLogger(__name__)

# mpv log-message levels -> app logger levels (delivered per request-log-messages)
MPV_LOG_LEVEL_MAP = {
    "fatal": logging.CRITICAL,
    "error": logging.ERROR,
    "warn": logging.WARNING,
    "info": logging.INFO,
}


class MPVService(PlaybackBackend):
    """Local playback backend powered by python-mpv-jsonipc.

    All MPV settings come from a config view (per-speaker values built from the
    config store, or the legacy env config when none is supplied)."""

    def __init__(self, config_view=None):
        self.config = config_view if config_view is not None else config
        self.device_name = self.config.MPV_DEVICE_NAME
        self._bt_checker = BluetoothAudioChecker()
        # audio-output death tracking (see _observe_ao_health): set BEFORE the
        # mpv process is created — the log handler is live from the first event
        self._ao_dead = False

        # python-mpv-jsonipc wires mpv's log stream via CONSTRUCTOR kwargs only
        # (log_handler + loglevel -> mpv's request-log-messages); assigning the
        # attribute post-construction is a silent no-op. loglevel "warn"
        # delivers warn/error/fatal (no v/debug firehose).
        def _mpv_log(level, prefix, text):
            logger.log(
                MPV_LOG_LEVEL_MAP.get(level, logging.DEBUG),
                f"[mpv:{self.device_name}] {level}: {text}".strip(),
            )
            self._observe_ao_health(level, text)

        mpv_kwargs = dict(
            ipc_socket=self.config.MPV_IPC_SOCKET,
            idle="yes",
            audio_display="no",
            force_window="no",
            really_quiet=True,
            ytdl=False,
            log_handler=_mpv_log,
            loglevel="warn",
            cache="yes" if self.config.MPV_CACHE_ENABLED else "no",
            cache_secs=max(5, self.config.MPV_CACHE_SECS),
            demuxer_max_bytes=self.config.MPV_DEMUXER_MAX_BYTES,
            demuxer_max_back_bytes=self.config.MPV_DEMUXER_MAX_BACK_BYTES,
            audio_buffer=max(0.2, float(self.config.MPV_AUDIO_BUFFER_SECONDS)),
        )
        # Only attach --log-file when explicitly configured. A None kwarg leaks
        # through the wrapper as a literal --log-file=None (mpv then opens a
        # file named "None"); mpv log routing goes through the app logger.
        if self.config.MPV_LOG_FILE:
            mpv_kwargs["log_file"] = self.config.MPV_LOG_FILE
        # Reserved for the USB-DAC output backburner item: direct ALSA output.
        audio_device = getattr(self.config, "MPV_AUDIO_DEVICE", "") or ""
        if audio_device:
            mpv_kwargs["audio_device"] = audio_device

        # The sound chain: DSP master on → compose (room correction + the
        # chosen global EQ preset) → compile; off = bypass (no filters at
        # all). Both steps live in app/services/sound_profile.py; the same
        # composition rules power the manager's hot-apply path.
        dsp = bool(getattr(self.config, "MPV_DSP_ENABLED", True))
        af, errors = "", []
        if dsp:
            composed, warnings = compose_profiles(
                getattr(self.config, "MPV_ROOM_CORRECTION", None),
                getattr(self.config, "MPV_SOUND_PRESET_PROFILE", None))
            for w in warnings:
                logger.warning(f"[mpv:{self.device_name}] composed profile: {w}")
            af, errors = compile_snd_profile(composed)
            if errors:
                logger.warning(f"[mpv:{self.device_name}] sound chain rejected: {errors}")
        if af:
            mpv_kwargs["af"] = af
            logger.info(f"[mpv:{self.device_name}] sound chain: {af}")

        self.player = mpv.MPV(**mpv_kwargs)

        # Explicitly unmute MPV on startup
        try:
            self.player.command("set_property", "mute", False)
            self.player.command("set_property", "volume", 50.0)
        except Exception as e:
            logger.warning(f"Failed to explicitly unset mute on startup: {e}")

        self.player.mute = False
        self.player.volume = 50.0

        if self.config.MPV_MSG_LEVEL:
            self.player.msg_level = self.config.MPV_MSG_LEVEL

        self._playback_active = False
        self._last_track_finished_at = 0.0

        # Register event listeners directly through the wrapper
        self.player.bind_property_observer("idle-active", self._handle_idle_active)
        self.player.bind_event("end-file", self._handle_end_file)

    def _emit_track_finished(self, reason: str, error=None):
        import time
        now = time.monotonic()
        if now - self._last_track_finished_at < 1.0:
            return

        self._last_track_finished_at = now
        self._playback_active = False
        logger.info("MPV track finished (reason=%s), emitting TRACK_FINISHED", reason)
        try:
            from app.core import event_bus, EventType, Event
            payload = {"Reason": reason, "device_name": self.device_name}
            if error is not None:
                payload["error"] = error
            event_bus.emit(Event(type=EventType.TRACK_FINISHED, payload=payload))
        except Exception as e:
            logger.error("Failed to emit TRACK_FINISHED from MPV event: %s", e)

    def _handle_idle_active(self, name, value):
        if value:
            # Player became idle (can happen from EOF, STOP, etc.)
            self._playback_active = False

    def _handle_end_file(self, event):
        reason = event.get("reason")
        if reason in ("eof", "error"):
            self._emit_track_finished(reason, error=event.get("file_error"))

    async def apply_sound_profile(self, profile: dict) -> Dict:
        """Set the 'af' property on the RUNNING mpv over json-IPC. The caller
        (the manager) passes the ALREADY-COMPOSED profile — room correction
        + the chosen preset — or {} for the bypass-clear. This method only
        touches the live process; persistence is the manager's job."""
        af, errors = compile_snd_profile(profile)
        if errors:
            return {"ok": False, "errors": errors}
        try:
            self.player.af = af   # property set via json-IPC wrapper
            logger.info(f"[mpv:{self.device_name}] sound chain applied: {af or '(clear)'}")
            return {"ok": True, "af": af, "supported": True}
        except Exception as e:
            logger.warning(f"[mpv:{self.device_name}] af set failed: {e}")
            return {"ok": False, "errors": [f"mpv rejected the filter chain: {e}"]}

    def _observe_ao_health(self, level: str, text: str) -> None:
        """Track mpv audio-output death (the USB-DAC direct route): pulling the
        card mid-play kills the ALSA output and mpv keeps 'playing' into the
        dead handle (`snd_pcm_status: No such device`) — every later resume
        would keep failing until a real teardown. Only MARK it here: the heal
        runs where playback is actually driven (play_media/resume/
        ensure_connected). Re-setting the audio-device does NOT revive the
        pipeline — verified live on the ZD3 (2026-10-09)."""
        if level != "error":
            return
        low = (text or "").lower()
        if "snd_pcm_status" in low or "no such device" in low or \
                "could not open/initialize audio" in low:
            self._ao_dead = True

    def _heal_dead_ao(self) -> None:
        """The user's own recipe ('stop and then play'), made automatic: a full
        teardown is the only cure for a dead ALSA output — the next play opens
        a fresh one. Mirrors stop()'s no-event discipline (_playback_active
        off BEFORE the mpv command, so the end-file reason 'stop' never
        advances the queue)."""
        self._playback_active = False
        try:
            self.player.command("stop")
            logger.info(f"[mpv:{self.device_name}] dead audio output torn down "
                        f"(device was gone?) — the next start opens a fresh one")
        except Exception as e:
            logger.warning(f"[mpv:{self.device_name}] dead-AO teardown failed: {e}")
        finally:
            self._ao_dead = False

    async def play_media(self, url: str, media_info: dict = None, content_type: str = "audio/mp3") -> bool:
        if self._ao_dead:
            self._heal_dead_ao()   # a fresh loadfile needs a live output
        readiness = self.get_output_readiness()
        if not readiness.get("ready", False):
            logger.warning("Output not ready: %s", readiness)
            return False

        try:
            self.player.loadfile(url, "replace")
            title = (media_info or {}).get("title") if media_info else None
            if title:
                self.player.force_media_title = title
            
            # Restore existing volume state instead of overriding it
            try:
                # Get the current internal wrapper volume or default
                current_vol = getattr(self.player, "volume", 50.0) 
                is_muted = getattr(self.player, "mute", False)

                self.player.command("set_property", "mute", is_muted)
                self.player.command("set_property", "volume", current_vol)
            except Exception as cmd_e:
                logger.warning("Failed forced socket properties fallback: %s", cmd_e)

            self.player.pause = False
            
            logger.info("Playing media locally via python-mpv-jsonipc: %s", url)
            self._playback_active = True
            return True
        except Exception as e:
            logger.error(f"Failed to play media: {e}")
            return False

    async def pause(self) -> bool:
        self.player.pause = True
        return True

    async def resume(self) -> bool:
        if self._ao_dead:
            self._heal_dead_ao()
            # a resume cannot follow the teardown — the caller must mark
            # stopped; the NEXT play opens a fresh output
            return False
        self.player.pause = False
        return True

    async def stop(self) -> bool:
        self._playback_active = False
        try:
            self.player.command("stop")
        except Exception:
            return False
        return True

    async def set_volume(self, volume: float) -> bool:
        mpv_volume = max(0.0, min(1.0, volume)) * 100.0
        try:
            self.player.command("set_property", "volume", mpv_volume)
            if mpv_volume > 0:
                self.player.command("set_property", "mute", False)
        except Exception:
            # Fallback to standard property setters
            self.player.volume = mpv_volume
            if self.player.mute and mpv_volume > 0:
                self.player.mute = False
        return True

    async def get_volume(self) -> Optional[float]:
        try:
            val = self.player.volume
            return val / 100.0 if val is not None else None
        except Exception:
            return None

    async def set_volume_muted(self, muted: bool) -> bool:
        self.player.mute = bool(muted)
        return True

    async def get_volume_muted(self) -> Optional[bool]:
        try:
            return bool(self.player.mute)
        except Exception:
            return None

    def ensure_connected(self) -> dict:
        if self._ao_dead:
            self._heal_dead_ao()   # the state pass reaches this — tear down now
        audio_device = getattr(self.config, "MPV_AUDIO_DEVICE", "") or ""
        status = self._bt_checker.check_ready(audio_device or None)
        return {"connected": status.get("ready", False), "reconnected": False}

    async def get_status(self) -> Optional[dict]:
        try:
            idle_active = self.player.idle_active
            paused = self.player.pause
            path = getattr(self.player, "path", None)
            title = getattr(self.player, "media_title", None)
            duration = getattr(self.player, "duration", None)
            current_time = getattr(self.player, "time_pos", None)
            volume = getattr(self.player, "volume", None)
            muted = getattr(self.player, "mute", None)

            if idle_active is True or not path:
                player_state = "IDLE"
            elif paused is True:
                player_state = "PAUSED"
            else:
                player_state = "PLAYING"

            return {
                "device_name": self.device_name,
                "player_state": player_state,
                "media_title": title,
                "path": path,
                "idle_active": idle_active,
                "current_time": current_time,
                "duration": duration,
                "volume_level": (float(volume) / 100.0) if volume is not None else None,
                "volume_muted": bool(muted) if muted is not None else None,
                "backend": "mpv",
            }
        except Exception:
            return None

    def get_output_readiness(self) -> Dict:
        audio_device = getattr(self.config, "MPV_AUDIO_DEVICE", "") or ""
        return self._bt_checker.check_ready(audio_device or None)

    async def cleanup(self):
        try:
            self.player.terminate()
        except Exception:
            pass

def get_mpv_service(device_name: str = None, options: Optional[Dict] = None) -> MPVService:
    """Create a new MPVService instance for a speaker. Per-speaker settings
    (device name, IPC socket, later: audio_device) come from the config store
    via the mpv config view; shared MPV tuning comes from the mpv section."""
    from app.core.service_container import get_service
    from app.services.config_store import mpv_config_view
    try:
        config_service = get_service("config_service")
        view = mpv_config_view(config_service, device_name, options)
    except Exception as e:
        logger.warning("Config store unavailable for MPV view (%s) — using env config", e)
        view = config
    return MPVService(config_view=view)
