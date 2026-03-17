from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
from typing import Dict, Optional


logger = logging.getLogger(__name__)


class BluetoothAudioChecker:
    """Checks and optionally reconnects a configured Bluetooth speaker."""

    def __init__(
        self,
        speaker_mac: Optional[str] = None,
        auto_reconnect: bool = False,
        mpv_audio_device: Optional[str] = None,
    ):
        self.speaker_mac = (speaker_mac or "").strip()
        self.auto_reconnect = auto_reconnect
        self.mpv_audio_device = (mpv_audio_device or "").strip()

    def check_ready(self) -> Dict:
        if not self.speaker_mac:
            return {
                "ready": True,
                "configured": False,
                "message": "No BT speaker MAC configured",
            }

        if not shutil.which("bluetoothctl"):
            return {
                "ready": False,
                "configured": True,
                "message": "bluetoothctl not available",
                "speaker_mac": self.speaker_mac,
            }

        info = self._bluetoothctl_info(self.speaker_mac)
        if not info["exists"]:
            return {
                "ready": False,
                "configured": True,
                "speaker_mac": self.speaker_mac,
                "message": "Speaker not known to bluetoothctl",
            }

        if info["connected"]:
            return self._connected_response(info, message="BT speaker connected")

        if self.auto_reconnect:
            reconnect_ok = self._connect(self.speaker_mac)
            if reconnect_ok:
                recheck = self._bluetoothctl_info(self.speaker_mac)
                if recheck["connected"]:
                    sink_name = self._default_sink()
                    return self._connected_response(recheck, message="BT speaker auto-reconnected")

        return {
            "ready": False,
            "configured": True,
            "speaker_mac": self.speaker_mac,
            "connected": False,
            "paired": info["paired"],
            "trusted": info["trusted"],
            "message": "BT speaker not connected",
        }

    def _bluetoothctl_info(self, mac: str) -> Dict:
        result = self._run_command(f"bluetoothctl info {shlex.quote(mac)}")
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        output_l = output.lower()
        exists = "device" in output_l and mac.lower() in output_l

        return {
            "exists": exists,
            "connected": "connected: yes" in output_l,
            "paired": "paired: yes" in output_l,
            "trusted": "trusted: yes" in output_l,
            "raw": output.strip(),
        }

    def _connect(self, mac: str) -> bool:
        logger.info("Attempting Bluetooth speaker reconnect for %s", mac)
        result = self._run_command(f"bluetoothctl connect {shlex.quote(mac)}")
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).lower()
        return "connection successful" in output or result.returncode == 0

    def _default_sink(self) -> Optional[str]:
        if not shutil.which("pactl"):
            return None
        result = self._run_command("pactl get-default-sink")
        sink = (result.stdout or "").strip()
        return sink or None

    def _default_sink_with_error(self):
        if not shutil.which("pactl"):
            return None, "pactl not installed"
        result = self._run_command("pactl get-default-sink")
        sink = (result.stdout or "").strip()
        if sink:
            return sink, None
        error = (result.stderr or "").strip() or f"pactl exit code {result.returncode}"
        return None, error

    def _connected_response(self, info: Dict, message: str) -> Dict:
        sink_name, sink_error = self._default_sink_with_error()
        sink_is_bt = bool(sink_name and "bluez" in sink_name.lower())
        uses_explicit_audio_device = bool(self.mpv_audio_device)

        if uses_explicit_audio_device:
            ready = True
            readiness_message = f"{message} (using explicit MPV_AUDIO_DEVICE)"
        elif sink_name is None:
            ready = True
            readiness_message = f"{message} (default sink unknown)"
        elif sink_is_bt:
            ready = True
            readiness_message = message
        else:
            ready = False
            readiness_message = (
                f"{message}, but default sink is not Bluetooth ({sink_name})"
            )

        return {
            "ready": ready,
            "configured": True,
            "speaker_mac": self.speaker_mac,
            "connected": True,
            "paired": info["paired"],
            "trusted": info["trusted"],
            "default_sink": sink_name,
            "default_sink_error": sink_error,
            "sink_is_bluetooth": sink_is_bt,
            "mpv_audio_device": self.mpv_audio_device or None,
            "message": readiness_message,
        }

    @staticmethod
    def _run_command(command: str) -> subprocess.CompletedProcess:
        uid = os.getuid()
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
        env = os.environ.copy()
        env.setdefault("XDG_RUNTIME_DIR", runtime_dir)
        env.setdefault("PULSE_SERVER", f"unix:{runtime_dir}/pulse/native")

        try:
            return subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=6,
                check=False,
                env=env,
            )
        except Exception as e:
            logger.warning("Command failed: %s (%s)", command, e)
            return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr=str(e))
