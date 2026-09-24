"""Output readiness checks for the mpv backend.

With per-speaker audio_device targeting (Phase C), mpv plays directly into
its configured pulse sink — the *system default sink* is irrelevant. The
checker therefore verifies the **targeted** sink exists (e.g. a BT speaker's
`bluez_sink.<MAC>.a2dp_sink` while the device is connected) and stays out of
the way otherwise.

History: this used to gate playback on the default sink being Bluetooth —
correct for the old follow-the-default-sink design, but it silently blocked
every play once per-speaker sinks became the routing model (found 2026-09-24,
RPi: BT playback dead with "Default sink is not Bluetooth … but mpv will use
it" while the targeted BT sink was perfectly present).
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class BluetoothAudioChecker:
    """Verifies that the sink a speaker targets actually exists in PulseAudio."""

    def check_ready(self, audio_device: Optional[str] = None) -> Dict:
        if not audio_device:
            return {
                "ready": True,
                "configured": True,
                "message": "No audio_device override — mpv uses its default output",
            }

        # mpv device ids look like 'pulse/<sink name>' (or '<ao>/<id>'); the
        # relevant pulse sink is the part after the slash.
        sink_name = audio_device.split("/", 1)[1] if "/" in audio_device else audio_device
        sink_is_bt = "bluez" in sink_name.lower()

        try:
            sinks = self._list_sinks()
        except Exception as e:
            # Cannot verify right now — do not block playback on a checker hiccup.
            logger.debug(f"Sink list unavailable, letting mpv try anyway: {e}")
            return {"ready": True, "configured": True, "sink": sink_name,
                    "sink_is_bluetooth": sink_is_bt,
                    "message": f"Could not verify sink ({e}) — letting mpv try"}

        if sink_name in sinks:
            return {
                "ready": True,
                "configured": True,
                "sink": sink_name,
                "sink_is_bluetooth": sink_is_bt,
                "message": f"Target sink present: {sink_name}",
            }

        return {
            "ready": False,
            "configured": True,
            "sink": sink_name,
            "sink_is_bluetooth": sink_is_bt,
            "message": f"Target sink not present (device disconnected?): {sink_name}",
        }

    def _list_sinks(self) -> List[str]:
        """PulseAudio sink names (from `pactl list sinks short`). Raises when
        pactl is unusable — the caller decides whether to block playback."""
        if not os.path.exists(os.path.join(self._runtime_dir(), "pulse", "native")):
            logger.debug("Pulse socket not present yet under %s", self._runtime_dir())
        result = self._run_command("pactl list sinks short")
        if result.returncode != 0:
            raise RuntimeError((result.stderr or "pactl failed").strip() or "pactl failed")
        sinks = []
        for line in (result.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1]:
                sinks.append(parts[1])
        return sinks

    @staticmethod
    def _runtime_dir() -> str:
        return os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"

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