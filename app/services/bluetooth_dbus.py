"""BlueZ over D-Bus (dbus-fast) — the async transport under BluetoothService.

Replaces the bluetoothctl subprocess layer (api-modernization era): the
regex parsers and the interactive scan-session puppeteering are gone. Speaks
to `org.bluez` directly over the system bus — the same API bluetoothctl
itself uses:

- org.freedesktop.DBus.ObjectManager.GetManagedObjects → device inventory
- Adapter1: SetDiscoveryFilter (BR/EDR only), StartDiscovery, StopDiscovery,
  RemoveDevice, Pairable
- Device1: Pair, Connect, Disconnect, Trusted, Connected, Name/Alias, UUIDs
- org.bluez.Battery1: Percentage
- org.bluez.Agent1 (auto-accept, NoInputNoOutput), registered with
  AgentManager1, so JustWorks A2DP pairing needs no interaction

Everything runs on a private event-loop thread; `BluetoothService` (the sync
facade, called via `asyncio.to_thread` by the routes) blocks on futures
posted to that loop. The PulseAudio layer (pactl) is unaffected — sinks are
PulseAudio objects, not BlueZ objects, so sink verification stays there.
"""

import asyncio
import logging
import re
import threading
from typing import Any, Callable, Dict, List, Optional

from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast.aio.message_bus import MessageBus
from dbus_fast.annotations import DBusObjectPath, DBusStr, DBusUInt32
from dbus_fast.service import ServiceInterface, dbus_method

logger = logging.getLogger(__name__)

AGENT_PATH = "/jukeplayer/bluez/agent"
A2DP_SINK_UUID = "0000110b-0000-1000-8000-00805f9b34fb"
COD_MAJOR_AUDIO = 4

_ERROR_RE = re.compile(r"org\.bluez\.Error\.(\w+)")


def is_audio_device(info: Dict[str, Any]) -> bool:
    """Heuristic: does this device look like an audio device? BlueZ Icon
    (audio-card/…) or the Class of Device major class (4 = Audio/Video)."""
    icon = str(info.get("icon") or "")
    if icon.startswith("audio"):
        return True
    cod = info.get("class")
    if cod is not None:
        return ((int(cod) >> 8) & 0x1F) == COD_MAJOR_AUDIO
    return False


def _prop(ifaces: Dict[str, Any], name: str, default: Any = None) -> Any:
    """Unwrap a property value (dbus-fast returns Variant-wrapped values)."""
    value = ifaces.get(name, default)
    if isinstance(value, Variant):
        value = value.value
    return value if value is not None else default


def _friendly_error(error_name: str, text: str = "") -> str:
    """org.bluez.Error.AlreadyExists → 'Device is already paired' — the
    route surfaces this text, so keep it human."""
    known = {
        "AlreadyExists": "Device is already paired",
        "AlreadyConnected": "Device is already connected",
        "ConnectionRejected": "Connection rejected",
        "Failed": "Operation failed",
        "NotReady": "Adapter not ready",
        "NotAvailable": "No agent available for pairing",
        "AuthenticationFailed": "Pairing authentication failed",
        "AuthenticationRejected": "Pairing rejected by the device",
        "AuthenticationCanceled": "Pairing canceled by the device",
        "DoesNotExist": "Device not known to BlueZ",
    }
    m = re.search(r"org\.bluez\.Error\.(\w+)", error_name or "")
    code = m.group(1) if m else (error_name or "UnknownError")
    return known.get(code, text.strip() or code)


class AutoAcceptAgent(ServiceInterface):
    """org.bluez.Agent1 — auto-accepts everything.

    Our speakers are JustWorks A2DP devices (NoInputNoOutput): pairing needs
    an agent that simply accepts. BlueZ calls the Request*/Authorize* methods
    during pairing; returning normally means "yes". The interactive methods
    (DisplayPasskey/DisplayPinCode) are not declared — a NoInputNoOutput
    agent is never asked to display anything."""

    def __init__(self) -> None:
        super().__init__("org.bluez.Agent1")

    @dbus_method()
    def Release(self) -> None:
        logger.debug("[BT-dbus] agent released")

    @dbus_method()
    def RequestPinCode(self, device: DBusObjectPath) -> DBusStr:
        return "0000"  # defensive accept — JustWorks never asks

    @dbus_method()
    def RequestConfirmation(self, device: DBusObjectPath, passkey: DBusUInt32) -> None:
        return None  # accept

    @dbus_method()
    def RequestAuthorization(self, device: DBusObjectPath) -> None:
        return None  # accept

    @dbus_method()
    def AuthorizeService(self, device: DBusObjectPath, uuid: DBusStr) -> None:
        return None  # accept (A2DP profile authorization)

    @dbus_method()
    def Cancel(self) -> None:
        pass


class BlueZDBusError(Exception):
    """org.bluez.Error.* replies from BlueZ (name + human text)."""

    def __init__(self, name: str, text: str = "") -> None:
        super().__init__(text or name)
        self.name = name
        self.text = text

    def __str__(self) -> str:
        return _friendly_error(self.name, self.text)


class BlueZDbus:
    """Async BlueZ client pinned to its own event loop.

    BluetoothService is a sync facade (routes call it via asyncio.to_thread,
    and some template contexts call it synchronously), so the client owns a
    private loop thread: `call()` posts a coroutine there and blocks on the
    result. The D-Bus connection and the pairing agent are created once."""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._bus: Optional[Any] = None
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()
        self._connect_error: Optional[str] = None
        self._adapter_path: Optional[str] = None
        self._agent = None
        self._agent_registered = False
        self._start_lock = threading.Lock()

    # --- lifecycle ----------------------------------------------------------------
    def ensure(self) -> None:
        """Start the loop thread (idempotent) and block until the bus is
        connected (or the connect error is recorded)."""
        with self._start_lock:
            if self._started.is_set():
                self._raise_if_unconnected()
                return
            thread = threading.Thread(target=self._run, name="bluez-dbus", daemon=True)
            thread.start()
            if not self._started.wait(timeout=15.0):
                raise RuntimeError("BlueZ D-Bus client did not start within 15s")
            self._raise_if_unconnected()

    def _raise_if_unconnected(self) -> None:
        if self._bus is None:
            raise RuntimeError(
                self._connect_error or "BlueZ D-Bus unavailable (system bus not connected)"
            )

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._connect())
        except Exception as e:
            logger.error(f"[BT-dbus] connect failed: {e}")
            self._connect_error = str(e)
            self._started.set()
            return
        self._started.set()
        loop.run_forever()

    async def _connect(self) -> None:
        self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        logger.info("[BT-dbus] system bus connected")
        # Register the pairing agent up front: Pair() without an agent can
        # fail for JustWorks devices depending on bluez's agent policy.
        self._agent = AutoAcceptAgent()
        self._bus.export(AGENT_PATH, self._agent)
        await self._call_raw(Message(
            destination="org.bluez", path="/org/bluez",
            interface="org.bluez.AgentManager1", member="RegisterAgent",
            body=[AGENT_PATH, "NoInputNoOutput"],
        ), timeout=10.0)
        await self._call_msg(Message(
            destination="org.bluez", path="/org/bluez",
            interface="org.bluez.AgentManager1", member="RequestDefaultAgent",
            body=[AGENT_PATH],
        ), timeout=10.0)
        self._agent_registered = True
        objects = await self._managed_objects()
        self._resolve_adapter(objects)
        logger.info(f"[BT-dbus] connected to org.bluez (adapter: {self._adapter_path})")

    # --- low-level ------------------------------------------------------------------
    async def _call_msg(self, msg: Message, timeout: float = 25.0) -> Any:
        reply = await asyncio.wait_for(self._bus.call(msg), timeout=timeout)
        if reply is None:
            raise RuntimeError("D-Bus call returned no reply")
        if reply.message_type == MessageType.ERROR:
            raise BlueZDBusError(reply.error_name or "",
                                 " ".join(str(b) for b in (reply.body or [])))
        return reply.body

    async def _set_adapter_prop(self, name: str, value: Variant) -> None:
        self._resolve_adapter(await self._get_managed_objects())
        if not self._adapter_path:
            raise RuntimeError("No Bluetooth adapter found")
        await self._call_msg(Message(
            destination="org.bluez", path=self._adapter_path,
            interface="org.freedesktop.DBus.Properties", member="Set",
            body=["org.bluez.Adapter1", name, value],
        ), timeout=10.0)

    async def _set_device_prop(self, device_path: str, name: str, value: Variant) -> None:
        await self._call_msg(Message(
            destination="org.bluez", path=device_path,
            interface="org.freedesktop.DBus.Properties", member="Set",
            body=["org.bluez.Device1", name, value],
        ), timeout=10.0)

    async def _get_managed_objects(self) -> Dict[str, Any]:
        reply = await self._call_msg(Message(
            destination="org.bluez", path="/",
            interface="org.freedesktop.DBus.ObjectManager", member="GetManagedObjects",
        ), timeout=15.0)
        return reply[0] if reply else {}

    def _resolve_adapter(self, objects: Dict[str, Any]) -> Optional[str]:
        if self._adapter_path and self._adapter_path in objects:
            return self._adapter_path
        for path, ifaces in objects.items():
            if "org.bluez.Adapter1" in ifaces:
                self._adapter_path = path
                return path
        return None

    def _device_path(self, mac: str) -> str:
        mac_u = mac.strip().upper().replace(":", "_")
        adapter = self._adapter_path or "/org/bluez/hci0"
        return f"{adapter}/dev_{mac_u}"

    @staticmethod
    def _device_from_ifaces(path: str, ifaces: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        dev = ifaces.get("org.bluez.Device1")
        if not dev:
            return None
        uuids = [str(u).lower() for u in (_prop(dev, "UUIDs") or [])]
        info: Dict[str, Any] = {
            "mac": str(_prop(dev, "Address") or "").upper(),
            "name": str(_prop(dev, "Alias") or _prop(dev, "Name") or "").strip(),
            "paired": bool(_prop(dev, "Paired")),
            "bonded": bool(_prop(dev, "Bonded", _prop(dev, "Paired"))),
            "trusted": bool(_prop(dev, "Trusted")),
            "connected": bool(_prop(dev, "Connected")),
            "uuids": uuids,
            "a2dp_sink": A2DP_SINK_UUID in uuids,
            "class": _prop(dev, "Class"),
            "icon": str(_prop(dev, "Icon") or ""),
        }
        info["audio"] = is_audio_device(info)
        return info

    # --- async API (one method per facade method) ------------------------------------
    async def status(self) -> Dict[str, Any]:
        objects = await self._get_managed_objects()
        adapter_path = self._resolve_adapter(objects)
        powered = None
        controller = None
        if adapter_path:
            a = objects.get(adapter_path, {}).get("org.bluez.Adapter1", {})
            powered = bool(_prop(a, "Powered"))
            controller = str(_prop(a, "Address") or "").upper()
        return {"powered": powered, "controller": controller}

    async def devices(self) -> List[Dict[str, Any]]:
        objects = await self._get_managed_objects()
        self._resolve_adapter(objects)
        out = []
        for path, ifaces in objects.items():
            device = self._device_from_ifaces(path, ifaces)
            if device:
                out.append(device)
        return out

    async def device_info(self, mac: str) -> Dict[str, Any]:
        target = mac.strip().upper()
        objects = await self._get_managed_objects()
        self._resolve_adapter(objects)
        for path, ifaces in objects.items():
            device = self._device_from_ifaces(path, ifaces)
            if device and device["mac"] == target:
                return device
        return {"mac": target, "paired": False, "bonded": False, "trusted": False,
                "connected": False, "name": "", "a2dp_sink": False, "class": None,
                "icon": "", "uuids": [], "audio": False}

    async def scan_window(self, seconds: float) -> List[Dict[str, Any]]:
        """BR/EDR-only discovery window. The filter keeps BLE beacons out of
        the list; devices discovered during the window persist as Device1
        objects, so the final GetManagedObjects snapshot is the result."""
        logger.info(f"[BT] Scan started ({seconds:.0f}s window, BR/EDR only)")
        objects = await self._get_managed_objects()
        adapter = self._resolve_adapter(objects)
        if not adapter:
            raise RuntimeError("No Bluetooth adapter found")
        await self._call_msg(Message(
            destination="org.bluez", path=adapter,
            interface="org.bluez.Adapter1", member="SetDiscoveryFilter",
            body=[{"Transport": Variant("s", "bredr")}],
        ), timeout=10.0)
        await self._call_msg(Message(
            destination="org.bluez", path=adapter,
            interface="org.bluez.Adapter1", member="StartDiscovery",
        ), timeout=10.0)
        await asyncio.sleep(seconds)
        await self._call_msg(Message(
            destination="org.bluez", path=adapter,
            interface="org.bluez.Adapter1", member="StopDiscovery",
        ), timeout=10.0)

        objects = await self._get_managed_objects()
        devices = []
        for path, ifaces in objects.items():
            device = self._device_from_ifaces(path, ifaces)
            if device:
                devices.append(device)
        audio = sum(1 for d in devices if d["audio"])
        logger.info(f"[BT] Scan finished: {len(devices)} device{'s' if len(devices) != 1 else ''} found "
                    f"({audio} audio) in {seconds:.0f}s")
        return devices

    async def pair_and_connect(self, mac: str) -> Dict[str, Any]:
        """pair → trust → connect (the card's one-click flow). Pairable is
        forced on so the pairing bonds — transparent re-pairing without
        persistent keys leaves pairings non-durable (found 2026-09-24)."""
        result: Dict[str, Any] = {"mac": mac, "paired": False, "trusted": False,
                                  "connected": False, "error": None}
        objects = await self._get_managed_objects()
        adapter = self._resolve_adapter(objects)
        dev_path = self._device_path(mac)
        try:
            await self._call_msg(Message(
                destination="org.bluez", path=adapter or "/org/bluez/hci0",
                interface="org.freedesktop.DBus.Properties", member="Set",
                body=["org.bluez.Adapter1", "Pairable", Variant("b", True)],
            ), timeout=10.0)
        except Exception as e:
            logger.debug(f"[BT-dbus] Pairable=True failed (continuing): {e}")

        logger.info(f"[BT] Pairing started for {mac}")
        try:
            await self._call_msg(Message(
                destination="org.bluez", path=dev_path,
                interface="org.bluez.Device1", member="Pair",
            ), timeout=45.0)
            result["paired"] = True
        except Exception as e:
            text = str(e)
            if "AlreadyExists" in text or "AlreadyPaired" in text:
                result["paired"] = True  # bluez reports this when already paired
            else:
                result["error"] = _friendly_error(text) or "Pairing failed"
                logger.warning(f"[BT] Pairing {mac} failed: {result['error']}")
                return result
        logger.info(f"[BT] Pairing {mac}: paired")

        try:
            await self._set_device_prop(dev_path, "Trusted", Variant("b", True))
            result["trusted"] = True
        except Exception as e:
            logger.warning(f"[BT] Trust {mac} failed: {e}")
        logger.info(f"[BT] Pairing {mac}: trusted={result['trusted']}")

        info = await self._connect_device(dev_path, mac)
        result["connected"] = info["connected"]
        result["paired"] = result["paired"] or info["paired"]
        result["trusted"] = result["trusted"] or info["trusted"]
        if not info["connected"]:
            result["error"] = info.get("error") or "Connect failed"
            logger.warning(f"[BT] Connect {mac} failed: {result['error']}")
        else:
            logger.info(f"[BT] Pairing {mac}: connected (name='{info.get('name')}')")
        if not info.get("bonded"):
            logger.warning(f"[BT] Pairing {mac} completed WITHOUT bonding — link keys "
                           f"will not persist across restarts (is the adapter bondable?)")
        return result

    async def _connect_device(self, device_path: str, mac: str) -> Dict[str, Any]:
        """Device1.Connect + post-state read (shared by pair and connect)."""
        try:
            await self._call_msg(Message(
                destination="org.bluez", path=device_path,
                interface="org.bluez.Device1", member="Connect",
            ), timeout=25.0)
        except Exception as e:
            text = str(e)
            if "AlreadyConnected" not in text:
                return {"connected": False, "paired": False, "bonded": False,
                        "name": "", "error": _friendly_error(text) or "Connect failed"}
        objects = await self._get_managed_objects()
        for path, ifaces in objects.items():
            device = self._device_from_ifaces(path, ifaces)
            if device and device["mac"] == mac.strip().upper():
                return {**device, "error": None}
        return {"connected": False, "paired": False, "bonded": False,
                "name": "", "error": "Device vanished after connect"}

    async def connect(self, mac: str) -> Dict[str, Any]:
        logger.info(f"[BT] Connecting {mac} …")
        info = await self._connect_device(self._device_path(mac), mac)
        if not info["connected"]:
            logger.warning(f"[BT] Connect {mac} failed: {info.get('error')}")
            return {"mac": mac, "connected": False, "paired": info["paired"], "error": info.get("error")}
        logger.info(f"[BT] Connected {mac} ({info.get('name')})")
        return {"mac": mac, "connected": True, "paired": info["paired"], "error": None}

    async def disconnect(self, mac: str) -> Dict[str, Any]:
        logger.info(f"[BT] Disconnecting {mac} …")
        await self._call_msg(Message(
            destination="org.bluez", path=self._device_path(mac),
            interface="org.bluez.Device1", member="Disconnect",
        ), timeout=15.0)
        objects = await self._get_managed_objects()
        connected = False
        for path, ifaces in objects.items():
            device = self._device_from_ifaces(path, ifaces)
            if device and device["mac"] == mac.strip().upper():
                connected = device["connected"]
        logger.info(f"[BT] Disconnect {mac}: connected={connected}")
        return {"mac": mac, "connected": connected}

    async def forget(self, mac: str) -> Dict[str, Any]:
        logger.info(f"[BT] Forgetting {mac} …")
        objects = await self._get_managed_objects()
        self._resolve_adapter(objects)
        removed = False
        for path, ifaces in objects.items():
            device = self._device_from_ifaces(path, ifaces)
            if device and device["mac"] == mac.strip().upper():
                await self._call_msg(Message(
                    destination="org.bluez", path=self._adapter_path or "/org/bluez/hci0",
                    interface="org.bluez.Adapter1", member="RemoveDevice",
                    body=[path],
                ), timeout=10.0)
                removed = True
        logger.info(f"[BT] Forget {mac}: removed={removed}")
        return {"mac": mac, "removed": removed}

    async def battery(self, mac: str) -> Optional[int]:
        """Battery percentage from BlueZ's Battery1 (native property read —
        no busctl). None when the device has no battery interface."""
        target = mac.strip().upper()
        objects = await self._get_managed_objects()
        for path, ifaces in objects.items():
            if "org.bluez.Device1" not in ifaces:
                continue
            if str(_prop(ifaces["org.bluez.Device1"], "Address") or "").upper() != target:
                continue
            battery = ifaces.get("org.bluez.Battery1")
            if not battery:
                return None
            value = _prop(battery, "Percentage")
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        return None

    async def shutdown(self) -> None:
        if self._bus:
            try:
                await self._bus.disconnect()
            except Exception:
                pass
            self._bus = None