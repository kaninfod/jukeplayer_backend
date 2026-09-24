"""Bluetooth device management + mpv output readiness (Phase C).

This module is the SINGLE home for Bluetooth/system interactions:
- `BluetoothService` — blocking wrapper around `bluetoothctl` (system D-Bus,
  works as the app user, no sudo) and `pactl` (PulseAudio sink discovery) for
  the BT card. Methods block on network/radio I/O; routes call them via
  `asyncio.to_thread`.
- `BluetoothAudioChecker` — verifies that the sink an mpv speaker targets
  actually exists in PulseAudio (used by the mpv playback backend; imported
  by app/playback_backends/mpv.py via the playback_backends.bluetooth shim).

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

logger = logging.getLogger(__name__)

# A2DP Audio Sink service UUID (the profile we care about for speakers)
A2DP_SINK_UUID = "0000110b-0000-1000-8000-00805f9b34fb"

_MAC_RE = re.compile(r"([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})")
_DEVICE_LINE_RE = re.compile(r"^(?:\[NEW\]\s+)?Device\s+([0-9A-Fa-f:]{17})\s+(.+)$")
_CONTROLLER_RE = re.compile(r"Controller\s+([0-9A-Fa-f:]{17})")
_UUID_RE = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")
_CLASS_RE = re.compile(r"Class:\s*0x([0-9A-Fa-f]+)")
_ICON_RE = re.compile(r"Icon:\s*(\S+)")

# CoD major device class 4 == Audio/Video
COD_MAJOR_AUDIO = 4


def is_audio_device(info: Dict[str, Any]) -> bool:
    """Heuristic: does this device look like an audio device? Uses the
    bluetoothctl Icon (audio-card/…) and the Class of Device major class
    (4 = Audio/Video). Unknown-class devices with a real name may still be
    audio — the UI keeps those visible."""
    icon = str(info.get("icon") or "")
    if icon.startswith("audio"):
        return True
    cod = info.get("class")
    if cod is not None:
        return ((int(cod) >> 8) & 0x1F) == COD_MAJOR_AUDIO
    return False


def parse_devices(output: str) -> List[Dict[str, str]]:
    """Parse `bluetoothctl devices` output → [{"mac", "name"}]."""
    devices = []
    seen = set()
    for line in output.splitlines():
        match = _DEVICE_LINE_RE.match(line.strip())
        if not match:
            continue
        mac, name = match.group(1).upper(), match.group(2).strip()
        if mac in seen:
            continue
        seen.add(mac)
        devices.append({"mac": mac, "name": name})
    return devices


def parse_info(output: str) -> Dict[str, Any]:
    """Parse `bluetoothctl info <MAC>` output → flags + name + uuids."""
    info: Dict[str, Any] = {"paired": False, "bonded": False, "trusted": False,
                            "connected": False, "name": "", "a2dp_sink": False,
                            "class": None, "icon": ""}
    uuids = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Name:"):
            info["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Paired:"):
            info["paired"] = "yes" in line
        elif line.startswith("Trusted:"):
            info["trusted"] = "yes" in line
        elif line.startswith("Connected:"):
            info["connected"] = "yes" in line
        elif line.startswith("Bonded:"):
            info["bonded"] = "yes" in line
        elif line.startswith("Class:"):
            cm = _CLASS_RE.search(line)
            if cm:
                info["class"] = int(cm.group(1), 16)
        elif line.startswith("Icon:"):
            im = _ICON_RE.search(line)
            if im:
                info["icon"] = im.group(1)
        elif line.startswith("UUID:"):
            m = _UUID_RE.search(line)
            if m:
                uuids.append(m.group(1).lower())
    info["uuids"] = uuids
    info["a2dp_sink"] = A2DP_SINK_UUID in uuids
    info["audio"] = is_audio_device(info)
    return info


def parse_pactl_sinks(output: str) -> List[Dict[str, str]]:
    """Parse `pactl list sinks short` → [{"index", "name", "state"}]."""
    sinks = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 5:
            sinks.append({"index": parts[0], "name": parts[1], "state": parts[-1].strip()})
    return sinks


def parse_scan_attributes(text: str) -> Dict[str, Dict[str, Any]]:
    """Collect Class/Icon attributes from a scan session's [CHG]/[NEW]
    Device lines → {MAC: {"class": int|None, "icon": str}}."""
    attrs: Dict[str, Dict[str, Any]] = {}
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"(?:\[NEW\]\s+|\[CHG\]\s+)?Device\s+([0-9A-Fa-f:]{17})\s+(.+)$", line)
        if not m:
            continue
        mac = m.group(1).upper()
        rest = m.group(2)
        entry = attrs.setdefault(mac, {"class": None, "icon": ""})
        cm = _CLASS_RE.search(rest)
        if cm:
            entry["class"] = int(cm.group(1), 16)
        im = _ICON_RE.search(rest)
        if im:
            entry["icon"] = im.group(1)
    return attrs


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


_SINK_MAC_RE = re.compile(r"bluez_sink\.([0-9A-Fa-f_]{17})\.")


def mac_from_sink_id(sink_id: Optional[str]) -> Optional[str]:
    """Inverse of pulse_sink_for_mac: extract the device MAC (colons) from an
    mpv audio-device id like 'pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink'.
    Returns None for non-bluetooth sinks."""
    if not sink_id:
        return None
    m = _SINK_MAC_RE.search(sink_id)
    return m.group(1).replace("_", ":").upper() if m else None


def _first_error_line(output: str) -> str:
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Failed") or "failed" in line.lower() or "error" in line.lower():
            return line
    return (output.strip()[:200] or "Command failed")


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
    """Blocking wrapper around bluetoothctl + pactl for the BT card. Callers
    run these methods via asyncio.to_thread (they wait on network/radio I/O)."""

    SCAN_SECONDS = 12.0
    WATCHDOG_INTERVAL = 30.0

    def __init__(self):
        # watchdog backoff state per MAC: {"attempts": n, "not_before": ts}
        self._watchdog_state: Dict[str, Dict[str, Any]] = {}

    # --- subprocess plumbing ---------------------------------------------------
    @staticmethod
    def _run(*args: str, timeout: float = 15.0) -> str:
        try:
            result = subprocess.run(
                list(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                text=True,
            )
            return result.stdout or ""
        except subprocess.TimeoutExpired:
            logger.warning("Command timed out: %s", " ".join(args))
            return ""

    def _ctl(self, *args: str, timeout: float = 15.0) -> str:
        return self._run("bluetoothctl", *args, timeout=timeout)

    # --- adapter / devices ------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        show = self._run("bluetoothctl", "show", timeout=5.0)
        powered = None
        controller = None
        for line in show.splitlines():
            line = line.strip()
            m = _CONTROLLER_RE.match(line)
            if m and controller is None:
                controller = m.group(1).upper()
            if line.startswith("Powered:"):
                powered = "yes" in line
        return {"powered": powered, "controller": controller}

    def info(self, mac: str) -> Dict[str, Any]:
        return parse_info(self._ctl("info", mac, timeout=8.0))

    def devices(self, timeout: float = 8.0) -> List[Dict[str, Any]]:
        output = self._ctl("devices", timeout=timeout)
        devices = []
        for entry in parse_devices(output):
            devices.append({**entry, **self.info(entry["mac"])})
        return devices

    def scan(self, seconds: Optional[float] = None) -> List[Dict[str, Any]]:
        """Open a scan window (keeping one bluetoothctl session alive so bluez
        keeps discovering), restricted to BR/EDR (classic) transport so the
        BLE-beacon junk nearby stays out of the list. Collects every device
        seen with its flags + Class/Icon attributes."""
        seconds = float(seconds or self.SCAN_SECONDS)
        logger.info(f"[BT] Scan started ({seconds:.0f}s window, BR/EDR only)")

        import time
        proc = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        text = ""
        try:
            time.sleep(0.5)
            assert proc.stdin
            # BR/EDR-only discovery: LE beacons are not audio devices
            proc.stdin.write("menu scan\ntransport bredr\nback\nscan on\n")
            proc.stdin.flush()
            time.sleep(seconds)
            proc.stdin.write("scan off\ndevices\n")
            proc.stdin.flush()
            time.sleep(1.0)
            proc.stdin.write("quit\n")
            proc.stdin.flush()
            try:
                text, _ = proc.communicate(timeout=10.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                text = proc.communicate()[0] or ""
        except Exception:
            proc.kill()
            proc.wait()
            raise

        logger.debug(f"[BT] Scan session collected {len(text.splitlines())} output lines")
        attrs = parse_scan_attributes(text)
        devices = []
        seen = set()
        for entry in parse_devices(text):
            if entry["mac"] in seen:
                continue
            seen.add(entry["mac"])
            device = {**entry, **self.info(entry["mac"])}
            extra = attrs.get(entry["mac"], {})
            if extra.get("class") is not None:
                device["class"] = extra["class"]
            if extra.get("icon"):
                device["icon"] = extra["icon"]
            device["audio"] = is_audio_device(device)
            devices.append(device)
        audio = sum(1 for d in devices if d["audio"])
        logger.info(f"[BT] Scan finished: {len(devices)} device{'s' if len(devices) != 1 else ''} found "
                    f"({audio} audio) in {seconds:.0f}s")
        for d in devices:
            logger.debug(f"[BT]   {d['mac']} name='{d.get('name', '')}' audio={d['audio']} "
                         f"paired={d.get('paired')} connected={d.get('connected')}")
        return devices

    # --- mutations ----------------------------------------------------------------
    def pair_and_connect(self, mac: str) -> Dict[str, Any]:
        """The card's one-click flow: pair → trust → connect."""
        logger.info(f"[BT] Pairing started for {mac} (bondable on → pair → trust → connect)")
        # Ensure the adapter bonds during pairing — transparent re-pairing
        # (bluez 5.82 kernel-side path) completes without persistent keys,
        # leaving the pairing non-durable (found 2026-09-24, RPi).
        self._ctl("bondable", "on", timeout=10.0)
        result: Dict[str, Any] = {"mac": mac, "paired": False, "trusted": False,
                                  "connected": False, "error": None}
        pair_out = self._ctl("pair", mac, timeout=30.0)
        result["paired"] = "Pairing successful" in pair_out or self.info(mac)["paired"]
        if not result["paired"]:
            result["error"] = _first_error_line(pair_out) or "Pairing failed"
            logger.warning(f"[BT] Pairing {mac} failed: {result['error']}")
            return result
        logger.info(f"[BT] Pairing {mac}: paired")
        result["trusted"] = "trust succeeded" in self._ctl("trust", mac, timeout=10.0)
        logger.info(f"[BT] Pairing {mac}: trusted={result['trusted']}")
        logger.info(f"[BT] Connecting {mac} …")
        connect_out = self._ctl("connect", mac, timeout=25.0)
        info = self.info(mac)
        result["connected"] = info["connected"]
        if not info["connected"]:
            result["error"] = _first_error_line(connect_out) or "Connect failed"
            logger.warning(f"[BT] Connect {mac} failed: {result['error']}")
        else:
            logger.info(f"[BT] Pairing {mac}: connected (name='{info.get('name')}')")
        if not info["bonded"]:
            logger.warning(f"[BT] Pairing {mac} completed WITHOUT bonding — link keys "
                           f"will not persist across restarts (is the adapter bondable?)")
        return result

    def connect(self, mac: str) -> Dict[str, Any]:
        logger.info(f"[BT] Connecting {mac} …")
        connect_out = self._ctl("connect", mac, timeout=25.0)
        info = self.info(mac)
        if not info["connected"]:
            error = _first_error_line(connect_out) or "Connect failed"
            logger.warning(f"[BT] Connect {mac} failed: {error}")
            return {"mac": mac, "connected": False, "paired": info["paired"], "error": error}
        logger.info(f"[BT] Connected {mac} ({info.get('name')})")
        return {"mac": mac, "connected": True, "paired": info["paired"], "error": None}

    def disconnect(self, mac: str) -> Dict[str, Any]:
        logger.info(f"[BT] Disconnecting {mac} …")
        self._ctl("disconnect", mac, timeout=15.0)
        connected = self.info(mac)["connected"]
        logger.info(f"[BT] Disconnect {mac}: connected={connected}")
        return {"mac": mac, "connected": connected}

    def forget(self, mac: str) -> Dict[str, Any]:
        logger.info(f"[BT] Forgetting {mac} …")
        self._ctl("remove", mac, timeout=10.0)
        removed = not self.info(mac)["paired"]
        logger.info(f"[BT] Forget {mac}: removed={removed}")
        return {"mac": mac, "removed": removed}

    # --- pulse integration ------------------------------------------------------------
    def bluez_sinks(self) -> List[Dict[str, str]]:
        output = self._run("pactl", "list", "sinks", "short", timeout=10.0)
        sinks = [s for s in parse_pactl_sinks(output) if s["name"].startswith("bluez_sink.")]
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

    def battery_percent(self, mac: str) -> Optional[int]:
        """Battery percentage from BlueZ's Battery1 interface (standard
        Battery Service). Returns None when the device does not expose it."""
        dev_path = f"/org/bluez/hci0/dev_{mac_to_underscored(mac)}"
        try:
            out = self._run("busctl", "get-property", "org.bluez", dev_path,
                            "org.bluez.Battery1", "Percentage", timeout=6.0)
        except Exception as e:
            logger.debug(f"[BT] Battery lookup failed for {mac}: {e}")
            return None
        m = re.search(r"(-?\d+)", out)
        return int(m.group(1)) if m else None

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

    def watchdog_tick(self) -> Dict[str, Any]:
        """One BT watchdog pass (Phase C hardening): for every BT-backed
        speaker in the store, verify its pulse sink is present; reconnect
        paired devices whose sink vanished mid-session (the shared BT chip
        drops links without app-visible errors — see ledger "BT hardening").
        Per-MAC backoff after failed attempts so a powered-off speaker does
        not get hammered every interval."""
        import time as _time
        from app.core.service_container import get_service
        from app.services.bluetooth_service import mac_from_sink_id  # self module

        try:
            speakers = get_service("config_service").speakers()
        except Exception as e:
            logger.debug(f"[BT watchdog] pass skipped: {e}")
            return {"checked": 0, "reconnected": [], "skipped": "store unavailable"}

        now = _time.monotonic()
        reconnected = []
        checked = 0
        for entry in speakers:
            mac = mac_from_sink_id((entry.get("options") or {}).get("audio_device"))
            if not mac:
                continue
            state = self._watchdog_state.get(mac, {})
            if now < state.get("not_before", 0):
                continue  # backing off after previous failures
            if self.sink_for_device(mac):
                continue  # healthy: sink present
            info = self.info(mac)
            if not info["paired"]:
                logger.debug(f"[BT watchdog] {mac} not paired — skipping (was it forgotten?)")
                continue
            logger.info(f"[BT watchdog] '{entry.get('name')}' ({mac}) lost its sink — reconnecting …")
            result = self.connect(mac)
            if result["connected"]:
                logger.info(f"[BT watchdog] Reconnected {mac} — resume playback from the UI if the track does not pick up automatically")
                self._watchdog_state.pop(mac, None)
                reconnected.append(mac)
            else:
                attempts = state.get("attempts", 0) + 1
                delay = min(300.0, 30.0 * (2 ** min(attempts, 4)))
                self._watchdog_state[mac] = {"attempts": attempts, "not_before": now + delay,
                                             "error": result.get("error")}
                logger.warning(f"[BT watchdog] Reconnect {mac} failed ({result.get('error')}) — retry in {delay:.0f}s")
        return {"checked": checked + len(speakers), "reconnected": reconnected}