from __future__ import annotations

import json
import logging
import os
import queue
import select
import socket
import subprocess
import threading
import time
from typing import Any
from typing import Dict, Optional
from .playback_backend import PlaybackBackend

from app.config import config
from app.services.bluetooth_audio_checker import BluetoothAudioChecker


logger = logging.getLogger(__name__)


class MPVService(PlaybackBackend):
    """Local playback backend powered by mpv JSON IPC."""

    def __init__(self):
        self.device_name = config.MPV_DEVICE_NAME #"Local MPV"
        self._process: Optional[subprocess.Popen] = None
        self._socket_path = config.MPV_IPC_SOCKET
        self._audio_device = self._normalize_audio_device(config.MPV_AUDIO_DEVICE)
        self._request_id = 1
        self._lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._ipc_write_lock = threading.Lock()
        self._ipc_conn_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending_events: Dict[int, threading.Event] = {}
        self._pending_responses: Dict[int, Dict[str, Any]] = {}
        self._command_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=256)
        self._command_thread: Optional[threading.Thread] = None
        self._stop_commands = threading.Event()
        self._command_retries = max(0, int(getattr(config, "MPV_IPC_COMMAND_RETRIES", 2)))
        self._command_retry_backoff_seconds = max(0.05, float(getattr(config, "MPV_IPC_RETRY_BACKOFF_SECONDS", 0.15)))
        self._loadfile_timeout_seconds = max(
            8.0,
            float(getattr(config, "MPV_LOADFILE_TIMEOUT_SECONDS", 14.0)),
        )
        self._status_lock = threading.Lock()
        self._status_cache: Dict[str, Any] = {
            "pause": None,
            "idle-active": True,
            "path": None,
            "media-title": None,
            "duration": None,
            "time-pos": None,
            "volume": None,
            "mute": None,
            "eof-reached": None,
        }
        self._ipc_socket: Optional[socket.socket] = None
        self._ipc_reader = None
        self._ipc_connected = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_monitor = threading.Event()
        self._last_track_finished_at = 0.0
        self._diag_interval_seconds = max(5, int(config.MPV_DIAGNOSTIC_INTERVAL_SECONDS))
        self._idle_diag_interval_seconds = max(
            self._diag_interval_seconds * 6,
            int(getattr(config, "MPV_IDLE_DIAGNOSTIC_INTERVAL_SECONDS", 120)),
        )
        self._readiness_refresh_seconds = max(
            self._diag_interval_seconds * 3,
            int(getattr(config, "MPV_READINESS_REFRESH_SECONDS", 60)),
        )
        self._stall_warning_seconds = max(20, int(config.MPV_STALL_WARNING_SECONDS))
        self._last_diag_log_at = 0.0
        self._last_idle_diag_log_at = 0.0
        self._last_progress_time: Optional[float] = None
        self._last_progress_at = 0.0
        self._stall_warning_emitted = False
        self._playback_active = False
        self._suppress_idle_finish_until = 0.0
        self._last_readiness_at = 0.0
        self._readiness_cache: Dict[str, Any] = {
            "ready": False,
            "configured": False,
            "message": "readiness not checked yet",
            "backend": "mpv",
        }
        self._bt_checker = BluetoothAudioChecker(
            speaker_mac=config.BT_SPEAKER_MAC,
            auto_reconnect=config.BT_AUTO_RECONNECT,
            mpv_audio_device=self._audio_device,
        )

    def play_media(self, url: str, media_info: dict = None, content_type: str = "audio/mp3") -> bool:
        readiness = self.get_output_readiness()
        if not readiness.get("ready", False):
            logger.warning("Bluetooth output not ready: %s", readiness)
            return False

        if not self._ensure_running():
            return False

        ok = self._send_command(["loadfile", url, "replace"])
        if ok:
            title = (media_info or {}).get("title") if media_info else None
            if title:
                self._send_command(["set_property", "force-media-title", title])
            self._send_command(["set_property", "pause", False])
            logger.info("Playing media locally via mpv: %s", url)
            now = time.monotonic()
            self._playback_active = True
            self._suppress_idle_finish_until = now + 2.0
            self._last_progress_time = None
            self._last_progress_at = now
            self._stall_warning_emitted = False
            self._maybe_log_diagnostics(force=True, trigger="play_media")
        return ok

    def pause(self) -> bool:
        return self._send_command(["set_property", "pause", True])

    def resume(self) -> bool:
        return self._send_command(["set_property", "pause", False])

    def stop(self) -> bool:
        self._suppress_idle_finish_until = time.monotonic() + 3.0
        self._playback_active = False
        return self._send_command(["stop"])

    def set_volume(self, volume: float) -> bool:
        mpv_volume = max(0.0, min(1.0, volume)) * 100.0
        return self._send_command(["set_property", "volume", mpv_volume])

    def get_volume(self) -> Optional[float]:
        value = self._get_property("volume")
        if value is None:
            return None
        try:
            return max(0.0, min(1.0, float(value) / 100.0))
        except Exception:
            return None

    def set_volume_muted(self, muted: bool) -> bool:
        return self._send_command(["set_property", "mute", bool(muted)])

    def get_volume_muted(self) -> Optional[bool]:
        value = self._get_property("mute")
        if value is None:
            return None
        return bool(value)

    def get_status(self) -> Optional[Dict]:
        if not self._ensure_running():
            return None
        with self._status_lock:
            paused = self._status_cache.get("pause")
            idle_active = self._status_cache.get("idle-active")
            path = self._status_cache.get("path")
            title = self._status_cache.get("media-title")
            duration = self._status_cache.get("duration")
            current_time = self._status_cache.get("time-pos")
            volume = self._status_cache.get("volume")
            muted = self._status_cache.get("mute")

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

    def get_output_readiness(self) -> Dict:
        return self._refresh_output_readiness(force=False)

    def cleanup(self):
        self._stop_monitor.set()
        self._stop_commands.set()
        self._close_ipc_connection()
        if self._command_thread and self._command_thread.is_alive():
            self._command_thread.join(timeout=1.0)
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=1.0)

        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass

        self._process = None
        try:
            if self._socket_path and os.path.exists(self._socket_path):
                os.unlink(self._socket_path)
        except Exception:
            pass

    def _ensure_running(self) -> bool:
        with self._process_lock:
            if self._process and self._process.poll() is None and os.path.exists(self._socket_path):
                self._start_monitor_thread()
                self._start_command_thread()
                return True

            started = self._start_mpv_process()
            if started:
                self._start_command_thread()
            return started

    def _start_mpv_process(self) -> bool:
        try:
            if self._socket_path and os.path.exists(self._socket_path):
                os.unlink(self._socket_path)
        except Exception:
            pass

        args = [
            config.MPV_BINARY,
            "--idle=yes",
            "--no-terminal",
            "--really-quiet",
            "--force-window=no",
            "--audio-display=no",
            f"--cache={'yes' if config.MPV_CACHE_ENABLED else 'no'}",
            f"--cache-secs={max(5, int(config.MPV_CACHE_SECS))}",
            f"--demuxer-max-bytes={config.MPV_DEMUXER_MAX_BYTES}",
            f"--demuxer-max-back-bytes={config.MPV_DEMUXER_MAX_BACK_BYTES}",
            f"--audio-buffer={max(0.2, float(config.MPV_AUDIO_BUFFER_SECONDS))}",
            f"--input-ipc-server={self._socket_path}",
        ]

        if self._audio_device:
            args.append(f"--audio-device={self._audio_device}")

        if config.MPV_MSG_LEVEL:
            args.append(f"--msg-level={config.MPV_MSG_LEVEL}")

        if config.MPV_LOG_FILE:
            args.append(f"--log-file={config.MPV_LOG_FILE}")

        extra = (config.MPV_EXTRA_ARGS or "").strip()
        if extra:
            args.extend(extra.split())

        try:
            runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
            env = os.environ.copy()
            env.setdefault("XDG_RUNTIME_DIR", runtime_dir)
            env.setdefault("PULSE_SERVER", f"unix:{runtime_dir}/pulse/native")

            self._process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
        except Exception as e:
            logger.error("Failed to start mpv process: %s", e)
            self._process = None
            return False

        deadline = time.time() + max(1, int(config.MPV_STARTUP_TIMEOUT_SECONDS))
        while time.time() < deadline:
            if self._process.poll() is not None:
                logger.error("mpv process exited during startup")
                return False
            if os.path.exists(self._socket_path):
                self._start_monitor_thread()
                logger.info("MPV backend started with IPC socket: %s", self._socket_path)
                return True
            time.sleep(0.05)

        logger.error("Timed out waiting for mpv IPC socket: %s", self._socket_path)
        return False

    def _normalize_audio_device(self, raw_value: Optional[str]) -> Optional[str]:
        device = (raw_value or "").strip()
        if not device:
            return None

        original = device
        device = device.rstrip(".")

        if "/" not in device and "bluez_output." in device:
            device = f"pipewire/{device}"

        if device != original:
            logger.warning(
                "Normalized MPV_AUDIO_DEVICE from '%s' to '%s'",
                original,
                device,
            )

        return device

    def _start_monitor_thread(self):
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._stop_monitor.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_events, daemon=True)
        self._monitor_thread.start()

    def _monitor_events(self):
        while not self._stop_monitor.is_set():
            if not self._ensure_running():
                time.sleep(0.5)
                continue

            try:
                if not self._ipc_connected.is_set():
                    self._connect_ipc()
                if not self._ipc_connected.is_set():
                    time.sleep(0.2)
                    continue

                try:
                    if not self._ipc_socket:
                        self._handle_connection_drop("mpv IPC socket unavailable")
                        time.sleep(0.1)
                        continue

                    ready, _, _ = select.select([self._ipc_socket], [], [], 1.0)
                    if not ready:
                        self._maybe_log_diagnostics(trigger="monitor_timeout")
                        continue

                    line = self._ipc_reader.readline()
                except (TimeoutError, OSError) as e:
                    self._handle_connection_drop(f"mpv IPC monitor read error: {e}")
                    time.sleep(0.1)
                    continue

                if not line:
                    self._handle_connection_drop("mpv IPC reader returned EOF")
                    time.sleep(0.1)
                    continue

                self._handle_event_line(line)
            except Exception as e:
                self._handle_connection_drop(f"mpv monitor error: {e}")
                time.sleep(0.2)

    def _connect_ipc(self):
        with self._ipc_conn_lock:
            if self._ipc_connected.is_set():
                return

            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(3.0)
                sock.connect(self._socket_path)
                sock.settimeout(None)
                reader = sock.makefile("r", encoding="utf-8", newline="\n")
                self._ipc_socket = sock
                self._ipc_reader = reader
                self._ipc_connected.set()
                self._register_monitor_observers()
            except Exception as e:
                self._handle_connection_drop(f"Failed to connect mpv IPC: {e}")

    def _start_command_thread(self):
        if self._command_thread and self._command_thread.is_alive():
            return
        self._stop_commands.clear()
        self._command_thread = threading.Thread(target=self._command_worker, daemon=True)
        self._command_thread.start()

    def _command_worker(self):
        while not self._stop_commands.is_set():
            try:
                task = self._command_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                command = task["command"]
                timeout_seconds = float(task["timeout_seconds"])
                attempts = int(task.get("attempts", 1))
                result = self._send_command_direct(command, timeout_seconds, attempts)
                task["response"] = result
            except Exception as e:
                logger.error("MPV command worker error: %s", e)
                task["response"] = None
            finally:
                done_event = task.get("done_event")
                if done_event is not None:
                    done_event.set()
                self._command_queue.task_done()

    def _register_monitor_observers(self):
        for observer_id, prop_name in [
            (1001, "eof-reached"),
            (1002, "idle-active"),
            (1003, "pause"),
            (1004, "path"),
            (1005, "media-title"),
            (1006, "duration"),
            (1007, "time-pos"),
            (1008, "volume"),
            (1009, "mute"),
        ]:
            self._send_ipc_message({"command": ["observe_property", observer_id, prop_name]})

    def _send_ipc_message(self, payload: Dict[str, Any]) -> bool:
        if not self._ipc_connected.is_set() or not self._ipc_socket:
            return False

        try:
            data = (json.dumps(payload) + "\n").encode("utf-8")
            with self._ipc_write_lock:
                if not self._ipc_socket:
                    return False
                self._ipc_socket.sendall(data)
            return True
        except Exception as e:
            self._handle_connection_drop(f"mpv IPC write failed: {e}")
            return False

    def _close_ipc_connection(self):
        self._ipc_connected.clear()

        if self._ipc_reader is not None:
            try:
                self._ipc_reader.close()
            except Exception:
                pass
            self._ipc_reader = None

        if self._ipc_socket is not None:
            try:
                self._ipc_socket.close()
            except Exception:
                pass
            self._ipc_socket = None

    def _handle_connection_drop(self, reason: str):
        if self._ipc_connected.is_set():
            logger.warning("MPV IPC disconnected: %s", reason)
        self._close_ipc_connection()

        with self._pending_lock:
            pending_ids = list(self._pending_events.keys())
            for req_id in pending_ids:
                self._pending_responses[req_id] = {"error": "connection-lost"}
                self._pending_events[req_id].set()

    def _handle_event_line(self, line: str):
        try:
            payload = json.loads(line)
        except Exception:
            return

        request_id = payload.get("request_id")
        if request_id is not None:
            with self._pending_lock:
                if request_id in self._pending_events:
                    self._pending_responses[request_id] = payload
                    self._pending_events[request_id].set()
            return

        event_name = payload.get("event")

        if event_name == "property-change":
            prop_name = payload.get("name")
            if prop_name in self._status_cache:
                with self._status_lock:
                    self._status_cache[prop_name] = payload.get("data")

        if event_name == "property-change" and payload.get("name") == "eof-reached":
            if payload.get("data") is True:
                logger.info("MPV property-change: eof-reached=True")
                self._emit_track_finished("eof-reached")
            return

        if event_name == "property-change" and payload.get("name") == "idle-active":
            self._handle_idle_active_change(bool(payload.get("data")))
            return

        if event_name != "end-file":
            return

        reason = payload.get("reason")
        error_text = payload.get("error")
        logger.info("MPV end-file event: reason=%s error=%s", reason, error_text)

        if reason == "eof":
            self._emit_track_finished("eof")
        elif reason == "error":
            logger.warning(
                "MPV playback ended with error (%s), emitting TRACK_FINISHED to continue playlist",
                error_text,
            )
            self._emit_track_finished("error", error_text)

    def _handle_idle_active_change(self, idle_active: bool):
        if not idle_active:
            return

        now = time.monotonic()
        if not self._playback_active:
            return
        if now < self._suppress_idle_finish_until:
            return

        status = self.get_status() or {}

        current_state = status.get("player_state")
        current_path = status.get("path")
        current_idle = status.get("idle_active")
        if current_state in ("PLAYING", "PAUSED") and current_path:
            logger.debug(
                "Ignoring stale idle-active event while playback is active (state=%s, path=%s)",
                current_state,
                current_path,
            )
            return
        if current_idle is False and current_path:
            logger.debug(
                "Ignoring idle-active fallback because current status is not idle (idle_active=%s, path=%s)",
                current_idle,
                current_path,
            )
            return

        logger.warning(
            "MPV idle-active fallback triggered without end-file; emitting TRACK_FINISHED (status=%s)",
            {
                "player_state": status.get("player_state"),
                "path": status.get("path"),
                "time": status.get("current_time"),
                "duration": status.get("duration"),
            },
        )
        self._emit_track_finished("idle-active-fallback")

    def _emit_track_finished(self, reason: str, error: Any = None):
        now = time.monotonic()
        if now - self._last_track_finished_at < 1.0:
            logger.debug("Skipping duplicate TRACK_FINISHED emission (reason=%s)", reason)
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
            self._maybe_log_diagnostics(force=True, trigger=f"track_finished:{reason}")
        except Exception as e:
            logger.error("Failed to emit TRACK_FINISHED from MPV event: %s", e)

    def _maybe_log_diagnostics(self, force: bool = False, trigger: str = "periodic"):
        now = time.monotonic()

        idle_hint = trigger in ("monitor_timeout", "idle")
        min_interval = self._idle_diag_interval_seconds if idle_hint else self._diag_interval_seconds
        last_logged_at = self._last_idle_diag_log_at if idle_hint else self._last_diag_log_at
        if not force and (now - last_logged_at) < min_interval:
            return

        status = self.get_status()

        if not status:
            logger.warning("MPV diagnostics (%s): backend status unavailable", trigger)
            if idle_hint:
                self._last_idle_diag_log_at = now
            else:
                self._last_diag_log_at = now
            return

        player_state = status.get("player_state")
        current_time = status.get("current_time")
        duration = status.get("duration")
        path = status.get("path")
        idle_active = status.get("idle_active")
        readiness_force = force or player_state == "PLAYING"
        readiness = self._refresh_output_readiness(force=readiness_force)

        if player_state == "PLAYING" and isinstance(current_time, (int, float)):
            if self._last_progress_time is None or current_time > (self._last_progress_time + 0.25):
                self._last_progress_time = float(current_time)
                self._last_progress_at = now
                self._stall_warning_emitted = False
            else:
                stalled_for = now - self._last_progress_at if self._last_progress_at else 0.0
                if stalled_for >= self._stall_warning_seconds and not self._stall_warning_emitted:
                    self._stall_warning_emitted = True
                    logger.warning(
                        "MPV possible stall: state=%s time=%s duration=%s stalled_for=%.1fs path=%s ready=%s sink=%s",
                        player_state,
                        current_time,
                        duration,
                        stalled_for,
                        path,
                        readiness.get("ready"),
                        readiness.get("default_sink"),
                    )

        logger.info(
            "MPV diagnostics (%s): state=%s time=%s duration=%s idle_active=%s ready=%s sink=%s sink_err=%s path=%s",
            trigger,
            player_state,
            current_time,
            duration,
            idle_active,
            readiness.get("ready"),
            readiness.get("default_sink"),
            readiness.get("default_sink_error"),
            path,
        )
        if idle_hint:
            self._last_idle_diag_log_at = now
        else:
            self._last_diag_log_at = now

    def _refresh_output_readiness(self, force: bool = False) -> Dict:
        now = time.monotonic()
        if not force and (now - self._last_readiness_at) < self._readiness_refresh_seconds:
            return dict(self._readiness_cache)

        readiness = self._bt_checker.check_ready()
        readiness["backend"] = "mpv"
        self._readiness_cache = readiness
        self._last_readiness_at = now
        return dict(readiness)

    def _get_property(self, name: str):
        with self._status_lock:
            if name in self._status_cache and self._status_cache[name] is not None:
                return self._status_cache[name]

        response = self._send_command_with_response(["get_property", name])
        if not response:
            return None
        if response.get("error") != "success":
            return None
        value = response.get("data")
        if name in self._status_cache:
            with self._status_lock:
                self._status_cache[name] = value
        return value

    def _send_command(self, command: list) -> bool:
        response = self._send_command_with_response(command)
        return bool(response and response.get("error") == "success")

    def _send_command_with_response(self, command: list) -> Optional[Dict]:
        if not self._ensure_running():
            return None

        is_loadfile = bool(command and command[0] == "loadfile")
        timeout_seconds = self._loadfile_timeout_seconds if is_loadfile else 3.5
        attempts = 1 if is_loadfile else (self._command_retries + 1)

        done_event = threading.Event()
        task = {
            "command": command,
            "timeout_seconds": timeout_seconds,
            "attempts": attempts,
            "done_event": done_event,
            "response": None,
        }

        try:
            self._command_queue.put(task, timeout=0.75)
        except queue.Full:
            logger.error("MPV command queue is full; dropping command: %s", command)
            return None

        backoff_total = max(0, attempts - 1) * self._command_retry_backoff_seconds
        wait_timeout = (float(task["timeout_seconds"]) * attempts) + backoff_total + 1.0
        if not done_event.wait(timeout=wait_timeout):
            logger.error("MPV command queue timed out after %.1fs (%s)", wait_timeout, command)
            return None

        return task.get("response")

    def _send_command_direct(self, command: list, timeout_seconds: float, attempts: int = 1) -> Optional[Dict]:
        if not self._ensure_running():
            return None

        for attempt in range(1, attempts + 1):
            with self._lock:
                req_id = self._request_id
                self._request_id += 1

            pending = threading.Event()
            with self._pending_lock:
                self._pending_events[req_id] = pending

            payload = {
                "command": command,
                "request_id": req_id,
            }

            if not self._ipc_connected.is_set():
                self._connect_ipc()
            if not self._ipc_connected.is_set() or not self._send_ipc_message(payload):
                with self._pending_lock:
                    self._pending_events.pop(req_id, None)
                    self._pending_responses.pop(req_id, None)
                logger.warning(
                    "MPV IPC command attempt %s/%s failed (%s): connection unavailable",
                    attempt,
                    attempts,
                    command,
                )
                self._handle_connection_drop("send_command_direct connection unavailable")
                if attempt < attempts:
                    time.sleep(self._command_retry_backoff_seconds)
                    continue
                return None

            if not pending.wait(timeout=timeout_seconds):
                with self._pending_lock:
                    self._pending_events.pop(req_id, None)
                    self._pending_responses.pop(req_id, None)
                logger.warning(
                    "MPV IPC command attempt %s/%s timed out after %.1fs (%s)",
                    attempt,
                    attempts,
                    timeout_seconds,
                    command,
                )
                self._handle_connection_drop("send_command_direct timeout")
                if attempt < attempts:
                    time.sleep(self._command_retry_backoff_seconds)
                    continue
                return None

            with self._pending_lock:
                response = self._pending_responses.pop(req_id, None)
                self._pending_events.pop(req_id, None)

            if response and response.get("error") == "connection-lost":
                logger.warning(
                    "MPV IPC command attempt %s/%s failed (%s): connection dropped",
                    attempt,
                    attempts,
                    command,
                )
                if attempt < attempts:
                    time.sleep(self._command_retry_backoff_seconds)
                    continue
                return None

            return response

        return None


_mpv_service_instance: Optional[MPVService] = None


def get_mpv_service() -> MPVService:
    global _mpv_service_instance
    if _mpv_service_instance is None:
        _mpv_service_instance = MPVService()
    return _mpv_service_instance
