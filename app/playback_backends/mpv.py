from __future__ import annotations

import logging
import os
from typing import Dict, Optional

# The user-requested library
import python_mpv_jsonipc as mpv

from app.config import config
from app.playback_backends.base import PlaybackBackend
from app.playback_backends.bluetooth import BluetoothAudioChecker

logger = logging.getLogger(__name__)


class MPVService(PlaybackBackend):
    """Local playback backend powered by python-mpv-jsonipc."""

    def __init__(self):
        self.device_name = config.MPV_DEVICE_NAME
        self._bt_checker = BluetoothAudioChecker()
        
        self.player = mpv.MPV(
            ipc_socket=config.MPV_IPC_SOCKET,
            idle="yes",
            audio_display="no",
            force_window="no",
            really_quiet=True,
            ytdl=False,
            log_file=config.MPV_LOG_FILE if config.MPV_LOG_FILE else None,
            cache="yes" if config.MPV_CACHE_ENABLED else "no",
            cache_secs=max(5, config.MPV_CACHE_SECS),
            demuxer_max_bytes=config.MPV_DEMUXER_MAX_BYTES,
            demuxer_max_back_bytes=config.MPV_DEMUXER_MAX_BACK_BYTES,
            audio_buffer=max(0.2, float(config.MPV_AUDIO_BUFFER_SECONDS))
        )
        
        # Explicitly unmute MPV on startup
        self.player.mute = False
        self.player.volume = 50.0

        if config.MPV_MSG_LEVEL:
            self.player.msg_level = config.MPV_MSG_LEVEL

        if config.MPV_EXTRA_ARGS:
            pass # Would parse extra args if needed, but not strictly required for JSON ipc wrapper like this

        self._playback_active = False
        self._last_track_finished_at = 0.0

        # Register event listeners directly through the wrapper
        self.player.bind_property_observer("idle-active", self._handle_idle_active)
        self.player.bind_property_observer("eof-reached", self._handle_eof)

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
            payload = {"Reason": reason}
            if error is not None:
                payload["error"] = error
            event_bus.emit(Event(type=EventType.TRACK_FINISHED, payload=payload))
        except Exception as e:
            logger.error("Failed to emit TRACK_FINISHED from MPV event: %s", e)

    def _handle_idle_active(self, name, value):
        if value:
            # Player became idle
            self._playback_active = False
            self._emit_track_finished("idle")

    def _handle_eof(self, name, value):
        if value:
            self._emit_track_finished("eof-reached")

    async def play_media(self, url: str, media_info: dict = None, content_type: str = "audio/mp3") -> bool:
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
        return self._bt_checker.check_ready()

    async def cleanup(self):
        try:
            self.player.terminate()
        except Exception:
            pass

_mpv_instance = None

def get_mpv_service() -> MPVService:
    global _mpv_instance
    if _mpv_instance is None:
        _mpv_instance = MPVService()
    return _mpv_instance

_mpv_instance = None

def get_mpv_service() -> MPVService:
    global _mpv_instance
    if _mpv_instance is None:
        _mpv_instance = MPVService()
    return _mpv_instance
