"""Live speaker management (Phase B): discover Chromecasts, add/remove
speakers from the web UI without a restart.

The config store stays the single source of truth: every change is persisted
there first, then applied to the live registry (SpeakersService) and the
broker (clients attached to a removed speaker are re-homed to the default
speaker). Removal order matters: store first (so a failure leaves the store
untouched), then the live side, then client re-homing.
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

KNOWN_BACKENDS = ("chromecast", "mpv")


def normalize_speaker_name(raw: Any) -> str:
    """'Living Room' -> 'living_room' (store format). connect() re-normalizes
    back to 'Living Room' for discovery matching."""
    return re.sub(r"\s+", "_", str(raw or "").strip()).lower()


class SpeakerManagerService:
    """Orchestrates store persistence + live registry + broker on every
    speaker change. Registered as the `speaker_manager` singleton."""

    def __init__(self, store, config_service, speakers_service, broker, bluetooth_service=None):
        self.store = store
        self.config_service = config_service
        self.speakers = speakers_service
        self.broker = broker
        self.bluetooth_service = bluetooth_service
        # reconnect backoff state per MAC (BT watchdog)
        self._reconnect_state: Dict[str, Dict[str, Any]] = {}

    # --- read --------------------------------------------------------------------
    def configured(self) -> List[Dict[str, Any]]:
        return self.config_service.speakers()

    def discover(self) -> List[Dict[str, Any]]:
        """Blocking mDNS scan (call via asyncio.to_thread). Each discovered
        Chromecast is mapped to store-name format and flagged when already
        configured, so the picker can hide duplicates."""
        from app.playback_backends.chromecast import discover_devices
        timeout = float(self.store.section("chromecast").get("discovery_timeout", 3))
        configured = {s["name"] for s in self.configured()}
        logger.info(f"[SpeakerManager] Chromecast discovery started (window {timeout:.0f}s)")
        devices = []
        for device in discover_devices(timeout=timeout):
            store_name = normalize_speaker_name(device.get("name", ""))
            if not store_name:
                continue
            devices.append({
                **device,
                "store_name": store_name,
                "configured": store_name in configured,
            })
        logger.info(f"[SpeakerManager] Chromecast discovery finished: {len(devices)} device{'s' if len(devices) != 1 else ''} found "
                    f"({sum(1 for d in devices if d['configured'])} already configured)")
        for d in devices:
            logger.debug(f"[SpeakerManager]   {d['name']} model={d.get('model')} host={d.get('host')} "
                         f"configured={d['configured']}")
        return devices

    # --- mutations (persist, then apply live) --------------------------------------
    def add_speaker(self, name: str, backend: str = "chromecast",
                    options: Optional[Dict[str, Any]] = None,
                    is_default: bool = False,
                    display_name: Optional[str] = None) -> Dict[str, Any]:
        """Add a speaker: construct it live, then persist to the store. If the
        store write fails, the live speaker is rolled back so the registry
        always matches the store. display_name is the optional UI label."""
        store_name = normalize_speaker_name(name)
        if not store_name:
            raise ValueError("Speaker name is required")
        backend_clean = (backend or "chromecast").strip().lower()
        if backend_clean not in KNOWN_BACKENDS:
            raise ValueError(f"Unknown backend '{backend_clean}' (known: {', '.join(KNOWN_BACKENDS)})")
        if store_name in {s["name"] for s in self.configured()}:
            raise ValueError(f"Speaker '{store_name}' is already configured")

        display = str(display_name or "").strip()
        entry = {"name": store_name, "backend": backend_clean,
                 "options": dict(options or {}), "is_default": bool(is_default),
                 "display_name": display}
        speaker = self.speakers.add_speaker(entry)  # raises on registry duplicates
        try:
            speakers = self.store.add_speaker(store_name, backend=backend_clean,
                                              options=entry["options"], is_default=bool(is_default),
                                              display_name=display)
        except Exception:
            self.speakers.remove_speaker(store_name)
            raise
        self._schedule_volume_sync(speaker)
        logger.info(f"[SpeakerManager] Added speaker '{store_name}' ({backend_clean}) — live, no restart")
        return next(s for s in speakers if s["name"] == store_name)

    async def remove_speaker(self, name: str) -> Dict[str, Any]:
        """Remove a speaker: stop playback, disconnect the backend, drop it
        from the registry, persist, re-point the default, re-home its clients."""
        store_name = normalize_speaker_name(name)
        removed = self.speakers.remove_speaker(store_name)
        if removed is None:
            raise ValueError(f"Speaker '{store_name}' is not configured")
        if removed.mediaplayer:
            player = removed.mediaplayer
            try:
                stop = getattr(player, "stop", None)
                if stop:
                    await stop()
            except Exception as e:
                logger.warning(f"[SpeakerManager] Stop failed for '{store_name}': {e}")
            backend = getattr(player, "playback_backend", None)
            disconnect = getattr(backend, "disconnect", None)
            if disconnect:
                try:
                    disconnect()
                except Exception as e:
                    logger.warning(f"[SpeakerManager] Disconnect failed for '{store_name}': {e}")
        remaining = self.store.remove_speaker(store_name)
        try:
            self.speakers.set_default_name(self.config_service.default_speaker_name())
        except ValueError:
            self.speakers.set_default_name(None)
        # bluetooth delete semantics: forget the device entirely
        # (Paired: no, Trusted: no, Connected: no)
        if removed.type == "bluetooth" and getattr(removed, "bt_mac", None) and self.bluetooth_service:
            try:
                await asyncio.to_thread(self.bluetooth_service.forget, removed.bt_mac)
            except Exception as e:
                logger.warning(f"[SpeakerManager] Forget failed for {store_name}: {e}")
        if self.broker:
            await self.broker.handle_speaker_removed(removed)
        logger.info(f"[SpeakerManager] Removed speaker '{store_name}' — live, no restart")
        return {"removed": store_name, "speakers": remaining}

    def set_default(self, name: str) -> Dict[str, Any]:
        """Flag one speaker as default in the store and in the live registry."""
        store_name = normalize_speaker_name(name)
        speakers = self.store.set_default_speaker(store_name)
        self.speakers.set_default_name(store_name)
        logger.info(f"[SpeakerManager] Default speaker set to '{store_name}'")
        return {"default": store_name, "speakers": speakers}

    def set_display_name(self, name: str, display_name: str) -> Dict[str, Any]:
        """Set a speaker's UI display label (empty string clears it, the
        technical name stays the matching key everywhere)."""
        store_name = normalize_speaker_name(name)
        speakers = self.store.set_speaker_display_name(store_name, display_name)
        entry = next((s for s in speakers if s["name"] == store_name), None)
        display = entry["display_name"] if entry else str(display_name or "").strip()
        live = self.speakers.get_speaker(speaker_name=store_name)
        if live:
            live.display_name = display
        logger.info(f"[SpeakerManager] Display name for '{store_name}' set to '{display}'")
        return {"name": store_name, "display_name": display, "speakers": speakers}

    # --- runtime state + connect/disconnect (Phase C.2) --------------------------------
    def update_speaker_states(self) -> Dict[str, Any]:
        """One pass over the speaker registry: refresh available/connected flags
        on every Speaker and reconnect BT speakers whose sink vanished mid-session.

        - chromecast: available = discovered on the network (zeroconf pings);
          connected = the cast socket is alive (true while playing)
        - bluetooth: connected = pulse sink present; available = paired or connected
        One updater, one cadence — no duplicate polling elsewhere."""
        import time as _time
        from app.playback_backends import chromecast as cc_mod
        now = _time.monotonic()
        reconnected = []
        cc_names = None
        try:
            cc_names = {normalize_speaker_name(n) for n in cc_mod.discovered_names()}
        except Exception as e:
            logger.debug(f"[SpeakerManager] CC discovery unavailable: {e}")

        for speaker in self.speakers.get_all_speakers().values():
            if speaker.type == "chromecast":
                if cc_names is not None:
                    speaker.available = normalize_speaker_name(speaker.speaker_name) in cc_names
                backend = getattr(speaker.mediaplayer, "playback_backend", None) if speaker.mediaplayer else None
                conn = getattr(backend, "is_connected", None)
                speaker.connected = bool(conn and conn())
            elif speaker.type == "bluetooth" and self.bluetooth_service:
                mac = getattr(speaker, "bt_mac", None)
                if not mac:
                    continue
                state = self._reconnect_state.get(mac, {})
                if now < state.get("not_before", 0):
                    continue  # backing off after failed reconnects
                sink = self.bluetooth_service.sink_for_device(mac)
                bt_info = self.bluetooth_service.info(mac)
                speaker.connected = sink is not None
                speaker.available = bool(bt_info.get("paired")) or sink is not None
                speaker.battery = self.bluetooth_service.battery_percent(mac, bt_info.get("uuids"))
                if not sink and bt_info.get("paired"):
                    if getattr(speaker, "user_disconnected", False):
                        # user handover: the speaker was deliberately handed
                        # to another device — auto-reconnect paused until the
                        # user presses Connect (marker persists in the store)
                        logger.debug(f"[SpeakerManager] '{speaker.speaker_name}' in user handover — auto-reconnect paused")
                        continue
                    logger.info(f"[SpeakerManager] '{speaker.speaker_name}' ({mac}) lost its sink — reconnecting …")
                    result = self.bluetooth_service.connect(mac)
                    if result["connected"]:
                        speaker.connected = True
                        speaker.available = True
                        self._reconnect_state.pop(mac, None)
                        reconnected.append(speaker.speaker_name)
                        logger.info(f"[SpeakerManager] Reconnected '{speaker.speaker_name}' — resume playback from the UI if needed")
                    else:
                        attempts = state.get("attempts", 0) + 1
                        delay = min(300.0, 30.0 * (2 ** min(attempts, 4)))
                        self._reconnect_state[mac] = {"attempts": attempts, "not_before": now + delay,
                                                      "error": result.get("error")}
                        logger.warning(f"[SpeakerManager] Reconnect {mac} failed ({result.get('error')}) — retry in {delay:.0f}s")
            else:
                # local speakers (e.g. analog): available when configured
                speaker.available = True
        return {"reconnected": reconnected}

    async def connect_speaker(self, name: str) -> Dict[str, Any]:
        """Connect a speaker's device. Bluetooth: bluetoothctl connect.
        (Chromecast speakers connect lazily on playback — no button.)"""
        speaker = self.speakers.get_speaker(speaker_name=name)
        if not speaker:
            raise ValueError(f"Speaker '{name}' is not configured")
        if speaker.type != "bluetooth":
            raise ValueError(f"'{name}' is not a Bluetooth speaker (type: {speaker.type})")
        if not self.bluetooth_service:
            raise ValueError("Bluetooth tools unavailable")
        mac = getattr(speaker, "bt_mac", None)
        if not mac:
            raise ValueError(f"'{name}' has no Bluetooth audio device")
        result = await asyncio.to_thread(self.bluetooth_service.connect, mac)
        speaker.connected = result["connected"]
        # explicit connect clears the user-handover marker (store + live flag)
        self._set_user_disconnected(name, False)
        if not result["connected"]:
            raise ValueError(result.get("error") or "Connect failed")
        return {"name": name, "connected": True}

    async def disconnect_speaker(self, name: str) -> Dict[str, Any]:
        speaker = self.speakers.get_speaker(speaker_name=name)
        if not speaker:
            raise ValueError(f"Speaker '{name}' is not configured")
        if speaker.type != "bluetooth":
            raise ValueError(f"'{name}' is not a Bluetooth speaker")
        if not self.bluetooth_service:
            raise ValueError("Bluetooth tools unavailable")
        mac = getattr(speaker, "bt_mac", None)
        result = await asyncio.to_thread(self.bluetooth_service.disconnect, mac)
        speaker.connected = result["connected"]
        # user intent: this speaker was deliberately handed over — pause the
        # watchdog auto-reconnect until the user connects again (persisted)
        self._set_user_disconnected(name, True)
        logger.info(f"[SpeakerManager] '{name}' disconnected by user — auto-reconnect paused (handover)")
        return {"name": name, "connected": result["connected"]}

    def _set_user_disconnected(self, name: str, flag: bool) -> None:
        """Persist the user-handover marker (speaker option) and mirror it on
        the live Speaker object. Store writes happen only on explicit user
        actions (disconnect/connect) — never in the 30s state pass."""
        speaker = self.speakers.get_speaker(speaker_name=name)
        if speaker:
            speaker.user_disconnected = flag
        try:
            self.store.set_speaker_option(normalize_speaker_name(name),
                                          "bt_user_disconnected", flag)
        except Exception as e:
            logger.warning(f"[SpeakerManager] could not persist handover flag for '{name}': {e}")

    # --- volume sync (shared with startup) --------------------------------
    async def sync_speaker_volume(self, speaker) -> None:
        """Connect (if needed) and pull the device's real volume into app state."""
        player = speaker.mediaplayer
        if not player:
            return
        backend = getattr(player, "playback_backend", None)
        try:
            is_connected = getattr(backend, "is_connected", None)
            if is_connected and not is_connected():
                ensure_connected = getattr(backend, "ensure_connected", None)
                if ensure_connected:
                    await asyncio.to_thread(ensure_connected)
            volume = await player.volume_manager.sync_volume_from_backend()
            logger.info(f"[SpeakerManager] Synced volume for {speaker.speaker_name}: {volume}")
        except Exception as e:
            logger.warning(f"[SpeakerManager] Volume sync skipped for {speaker.speaker_name}: {e}")

    async def sync_all_speaker_volumes(self) -> None:
        for speaker in list(self.speakers.get_all_speakers().values()):
            await self.sync_speaker_volume(speaker)

    def _schedule_volume_sync(self, speaker) -> None:
        """Pull the new speaker's real volume in the background (no-op when no
        running loop, e.g. in tests)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.sync_speaker_volume(speaker))