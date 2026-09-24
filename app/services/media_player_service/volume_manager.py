import logging

logger = logging.getLogger(__name__)

class VolumeManager:
    def __init__(self, playback_backend):
        self.playback_backend = playback_backend
        self._volume = 50  # Default volume level (0-100)
        self.is_muted = False
        # NOTE: no eager sync here. Syncing at construction connected every
        # device at startup (slow boot, noisy logs); the volume converges on
        # the first interaction or backend switch instead.

    @property
    def volume(self) -> int:
        return self._volume

    async def volume_up(self, step=5):
        new_volume = min(100, self._volume + step if step is not None else 0)
        return await self.set_volume(new_volume)

    async def volume_down(self, step=5):
        new_volume = max(0, self._volume - step if step is not None else 0)
        return await self.set_volume(new_volume)


    async def set_volume(self, volume=None):
        logger.debug(f"[set_volume] Requested volume: {volume}")
        try:
            self._volume = max(0, min(100, int(volume)))
        except Exception as e:
            logger.error(f"[set_volume] Failed to set current_volume from volume={volume}: {e}")
            self._volume = 0
        
        normalized_volume = self._volume / 100.0 if self._volume is not None else None

        if self._volume is not None:
            logger.info(f"Setting volume to {self._volume} (normalized: {normalized_volume}) on backend {self.playback_backend}")
            await self.playback_backend.set_volume(normalized_volume)

        logger.debug(f"[set_volume] current_volume set to: {self._volume}")
        return self._volume
    
    async def toggle_mute(self):
        """Toggle mute on the active playback backend."""
        try:
            # Get current mute state
            current_muted = await self.playback_backend.get_volume_muted()
            if current_muted is None:
                logger.error("Failed to get current mute state")
                return {"success": False, "muted": None}
            
            # Toggle mute
            new_muted = not current_muted
            success = await self.playback_backend.set_volume_muted(new_muted)
            
            if success:
                self.is_muted = new_muted
                logger.info(f"Volume {'muted' if new_muted else 'unmuted'}")
                return {"success": True, "muted": new_muted}
            else:
                self.is_muted = current_muted
                return {"success": False, "muted": current_muted}
        except Exception as e:
            logger.error(f"Failed to toggle mute: {e}")
            return {"success": False, "muted": None}
        
    def set_local_volume(self, volume, muted=None):
        """Update local volume state from a backend-reported value.
        Read-back only — never written to the device."""
        if volume is None:
            return self._volume
        try:
            self._volume = max(0, min(100, int(round(volume))))
        except (TypeError, ValueError):
            return self._volume
        if muted is not None:
            self.is_muted = bool(muted)
        return self._volume

    async def sync_volume_from_backend(self):
        """Pull the backend's current volume into local state (read-only —
        the old version wrote the value straight back to the device)."""
        backend_volume = await self.playback_backend.get_volume()
        logger.debug(f"[sync_volume_from_backend] volume from backend: {backend_volume}")
        if backend_volume is not None:
            self.set_local_volume(int(round(backend_volume * 100)))
        return self._volume