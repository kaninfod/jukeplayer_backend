from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class BluetoothAudioChecker:
    """Checks the system default audio sink to see if it is a Bluetooth device."""

    def __init__(self, **kwargs):
        pass

    def check_ready(self) -> Dict:
        sink_name, sink_error = self._default_sink_with_error()
        if sink_name is None:
            return {
                "ready": True,
                "configured": True,
                "message": f"Default sink unknown: {sink_error}",
            }

        sink_is_bt = bool(sink_name and "bluez" in sink_name.lower())
        if sink_is_bt:
            return {
                "ready": True,
                "configured": True,
                "sink_is_bluetooth": True,
                "message": "BT speaker connected as default sink",
            }

        return {
            "ready": False,
            "configured": True,
            "sink_is_bluetooth": False,
            "message": f"Default sink is not Bluetooth ({sink_name}) but mpv will use it",
        }

    def _default_sink_with_error(self):
        if not shutil.which("pactl"):
            return None, "pactl not installed"
        result = self._run_command("pactl get-default-sink")
        sink = (result.stdout or "").strip()
        if sink:
            return sink, None
        error = (result.stderr or "").strip() or f"pactl exit code {result.returncode}"
        return None, error

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
