"""Bluetooth device management for the web UI (Phase C).

Wraps `bluetoothctl` (system D-Bus — works as the app user, no sudo) and
`pactl` (PulseAudio sink discovery). Methods are blocking (network/radio I/O)
— routes call them via asyncio.to_thread, same pattern as chromecast
discovery.

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
    info: Dict[str, Any] = {"paired": False, "trusted": False, "connected": False,
                            "name": "", "a2dp_sink": False, "class": None, "icon": ""}
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


def _first_error_line(output: str) -> str:
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Failed") or "failed" in line.lower() or "error" in line.lower():
            return line
    return (output.strip()[:200] or "Command failed")


class BluetoothService:
    """Blocking wrapper around bluetoothctl + pactl for the BT card. Callers
    run these methods via asyncio.to_thread (they wait on network/radio I/O)."""

    SCAN_SECONDS = 12.0

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
        proc = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        text = ""
        try:
            import time
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

        attrs = parse_scan_attributes(text)
        logger.debug(f"[BT] Scan session collected {len(text.splitlines())} output lines")
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
        logger.info(f"[BT] Pairing started for {mac} (pair → trust → connect)")
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