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

    def __init__(self, store, config_service, speakers_service, broker):
        self.store = store
        self.config_service = config_service
        self.speakers = speakers_service
        self.broker = broker

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
        return devices

    # --- mutations (persist, then apply live) --------------------------------------
    def add_speaker(self, name: str, backend: str = "chromecast",
                    options: Optional[Dict[str, Any]] = None,
                    is_default: bool = False) -> Dict[str, Any]:
        """Add a speaker: construct it live, then persist to the store. If the
        store write fails, the live speaker is rolled back so the registry
        always matches the store."""
        store_name = normalize_speaker_name(name)
        if not store_name:
            raise ValueError("Speaker name is required")
        backend_clean = (backend or "chromecast").strip().lower()
        if backend_clean not in KNOWN_BACKENDS:
            raise ValueError(f"Unknown backend '{backend_clean}' (known: {', '.join(KNOWN_BACKENDS)})")
        if store_name in {s["name"] for s in self.configured()}:
            raise ValueError(f"Speaker '{store_name}' is already configured")

        entry = {"name": store_name, "backend": backend_clean,
                 "options": dict(options or {}), "is_default": bool(is_default)}
        speaker = self.speakers.add_speaker(entry)  # raises on registry duplicates
        try:
            speakers = self.store.add_speaker(store_name, backend=backend_clean,
                                              options=entry["options"], is_default=bool(is_default))
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

    # --- volume sync (shared with startup) -------------------------------------------
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