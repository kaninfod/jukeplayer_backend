"""Bluetooth device management + mpv output readiness.

Single home for Bluetooth/system interactions:
- `BluetoothService` — the sync facade over `app.services.bluetooth_dbus.BlueZDbus`
  (async BlueZ over D-Bus via dbus-fast, pinned to its own event-loop thread).
  Same public API as the bluetoothctl-wrapper era — only the transport changed:
  direct `org.bluez` calls (ObjectManager, Adapter1, Device1, Battery1, agent)
  instead of subprocesses + regex-parsed stdout.
- `BluetoothAudioChecker` — verifies that the sink an mpv speaker targets
  actually exists in PulseAudio (pactl). Sinks are PulseAudio objects, not
  BlueZ objects — this layer is not affected by the D-Bus port.

Audio-server context (see ledger): the Pi runs **PulseAudio +
pulseaudio-module-bluetooth** — pipewire's bluez monitor never registers A2DP
endpoints on this Pi 3 / bluez 5.82 stack, so PulseAudio provides the
endpoints and mpv targets pulse sinks via the speaker's `options.
audio_device` (verified format: `pulse/bluez_sink.<MAC>.a2dp_sink`).
"""

import logging
import re
import subprocess
from typing import Any, Dict, List, Optional

from app.services.bluetooth_dbus import (  # noqa: F401  (re-exports)
    A2DP_SINK_UUID,
    BlueZDbus,
    is_audio_device,
)

logger = logging.getLogger(__name__)

_SINK_MAC_RE = re.compile(r"bluez_sink\.([0-9A-Fa-f_]{17})\.")


def mac_to_underscored(mac: str) -> str:
    """AA:BB:CC:DD:EE:FF → AA_BB_CC_DD_EE_FF (pulse/bluez id format)."""
    return mac.strip().upper().replace(":", "_")


def pulse_sink_for_mac(sinks: List[Dict[str, str]], mac: str) -> Optional[str]:
    """Find the bluez a2dp sink for a device MAC → mpv device id
    ('pulse/<sink name>') or None if the device has no sink (not connected)."""
    wanted = f"bluez_sink.{mac_to_underscored(mac)}."
    for sink in sinks:
        if sink["name"].startswith(wanted):
            return f"pulse/{sink['name']}"
    return None


def mac_from_sink_id(sink_id: Optional[str]) -> Optional[str]:
    """Inverse of pulse_sink_for_mac: extract the device MAC (colons) from an
    mpv audio-device id like 'pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink'.
    Returns None for non-bluetooth sinks."""
    if not sink_id:
        return None
    m = _SINK_MAC_RE.search(sink_id)
    return m.group(1).replace("_", ":").upper() if m else None


class BluetoothAudioChecker:
    """Verifies that the sink a speaker targets actually exists in PulseAudio.

    With per-speaker audio_device targeting (Phase C), mpv plays directly into
    its configured pulse sink — the *system default sink* is irrelevant. The
    checker therefore verifies the **targeted** sink exists (e.g. a BT
    speaker's `bluez_sink.<MAC>.a2dp_sink` while the device is connected) and
    stays out of the way otherwise. History: it used to gate playback on the
    default sink being Bluetooth — correct for the old follow-the-default
    design, but it silently blocked every play once per-speaker sinks became
    the routing model (found 2026-09-24)."""

    def check_ready(self, audio_device: Optional[str] = None) -> Dict:
        if not audio_device:
            return {
                "ready": True,
                "configured": True,
                "message": "No audio_device override — mpv uses its default output",
            }

        # mpv device ids look like 'pulse/<sink name>'; the relevant pulse
        # sink is the part after the slash.
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
            logger.info(f"[BT] Target sink present: {sink_name}")
            return {
                "ready": True,
                "configured": True,
                "sink": sink_name,
                "sink_is_bluetooth": sink_is_bt,
                "message": f"Target sink present: {sink_name}",
            }

        logger.warning(f"[BT] Target sink not present (device disconnected?): {sink_name}")
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
        import os
        uid = os.getuid()
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
        env = os.environ.copy()
        env.setdefault("XDG_RUNTIME_DIR", runtime_dir)
        env.setdefault("PULSE_SERVER", f"unix:{runtime_dir}/pulse/native")
        try:
            result = subprocess.run(
                "pactl list sinks short", shell=True, capture_output=True,
                text=True, timeout=6, check=False, env=env,
            )
        except Exception as e:
            raise RuntimeError(f"pactl unavailable: {e}")
        if result.returncode != 0:
            raise RuntimeError((result.stderr or "pactl failed").strip() or "pactl failed")
        sinks = []
        for line in (result.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1]:
                sinks.append(parts[1])
        return sinks


class BluetoothService:
    """Sync facade over the BlueZ D-Bus layer. Callers run these methods via
    `asyncio.to_thread` (they wait on radio I/O); some template contexts call
    them synchronously — both work: `BlueZDbus` owns a private event loop and
    the facade blocks on futures posted to it."""

    SCAN_SECONDS = 12.0
    WATCHDOG_INTERVAL = 30.0

    def __init__(self):
        self._dbus = BlueZDbus()
        # watchdog backoff state per MAC: {"attempts": n, "not_before": ts}
        self._watchdog_state: Dict[str, Dict[str, Any]] = {}

    # --- transport over D-Bus (same shapes as the bluetoothctl era) ---------------
    def status(self) -> Dict[str, Any]:
        return self._dbus.call(self._dbus.status, timeout=8.0)

    def info(self, mac: str) -> Dict[str, Any]:
        return self._dbus.call(lambda: self._dbus.device_info(mac), timeout=10.0)

    def devices(self, timeout: float = 10.0) -> List[Dict[str, Any]]:
        return self._dbus.call(self._dbus.devices, timeout=timeout)

    def scan(self, seconds: Optional[float] = None) -> List[Dict[str, Any]]:
        """BR/EDR-only discovery window (SetDiscoveryFilter keeps the BLE
        beacons out). Same result shape as the bluetoothctl era."""
        window = float(seconds or self.SCAN_SECONDS)
        return self._dbus.call(lambda: self._dbus.scan_window(window),
                               timeout=window + 20.0)

    def pair_and_connect(self, mac: str) -> Dict[str, Any]:
        """The card's one-click flow: pair → trust → connect."""
        return self._dbus.call(lambda: self._dbus.pair_and_connect(mac), timeout=90.0)

    def connect(self, mac: str) -> Dict[str, Any]:
        return self._dbus.call(lambda: self._dbus.connect(mac), timeout=30.0)

    def disconnect(self, mac: str) -> Dict[str, Any]:
        return self._dbus.call(lambda: self._dbus.disconnect(mac), timeout=20.0)

    def forget(self, mac: str) -> Dict[str, Any]:
        return self._dbus.call(lambda: self._dbus.forget(mac), timeout=15.0)

    # --- pulse integration (unchanged) ----------------------------------------------
    @staticmethod
    def _pactl(timeout: float = 10.0) -> str:
        try:
            result = subprocess.run(
                ["pactl", "list", "sinks", "short"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=timeout, text=True,
            )
            return result.stdout or ""
        except subprocess.TimeoutExpired:
            logger.warning("pactl timed out")
            return ""
        except FileNotFoundError:
            logger.warning("pactl not available")
            return ""

    def bluez_sinks(self) -> List[Dict[str, str]]:
        output = self._pactl(timeout=10.0)
        sinks = []
        for line in output.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1].startswith("bluez_sink."):
                sinks.append({"index": parts[0], "name": parts[1],
                              "state": parts[-1].strip() if len(parts) >= 5 else ""})
        logger.debug(f"[BT] PulseAudio bluez sinks: {[s['name'] for s in sinks]}")
        return sinks

    def sink_for_device(self, mac: str) -> Optional[str]:
        """mpv device id ('pulse/<sink>') for a connected BT device, or None."""
        sink = pulse_sink_for_mac(self.bluez_sinks(), mac)
        if sink:
            logger.info(f"[BT] Audio sink for {mac}: {sink}")
        else:
            logger.info(f"[BT] No pulse sink for {mac} (not connected?)")
        return sink

    # --- battery ------------------------------------------------------------------
    def battery_percent(self, mac: str, uuids: Optional[List[str]] = None) -> Optional[int]:
        """Battery percentage from BlueZ's Battery1 interface. Returns None
        when the device does not expose a CLEAR reading — Logitech devices
        (fe61) route their vendor battery char through BlueZ's heuristic,
        which misreports (BOOM 3 showed a bogus 1%)."""
        try:
            value = self._dbus.call(lambda: self._dbus.battery(mac), timeout=8.0)
        except Exception as e:
            logger.debug(f"[BT] Battery lookup failed for {mac}: {e}")
            return None
        if value is None:
            return None
        # Prefix check: BlueZ reports full UUIDs ("0000fe61-0000-1000-..."),
        # so a bare-string list membership never matched — the old filter
        # silently never fired.
        if any("0000fe61" in (u or "").lower() for u in (uuids or [])) and value <= 10:
            logger.debug(f"[BT] Battery {value}% for {mac} looks like the Logitech "
                         f"vendor-char misreport — not a clear reading")
            return None
        return value

    # --- startup reconnect -------------------------------------------------------------
    def auto_connect_trusted(self) -> None:
        """Best-effort startup reconnect (design decision #3): attempt connect
        for every known device that is paired but disconnected, so a
        powered-on Boom is picked up after a reboot."""
        try:
            devices = self.devices()
        except Exception as e:
            logger.warning(f"[BluetoothService] startup connect skipped: {e}")
            return
        for device in devices:
            if device.get("paired") and not device.get("connected") and device.get("a2dp_sink"):
                try:
                    result = self.connect(device["mac"])
                    if result["connected"]:
                        logger.info(f"[BluetoothService] Auto-connected {device['name']} ({device['mac']})")
                except Exception as e:
                    logger.warning(f"[BluetoothService] Auto-connect failed for {device['mac']}: {e}")