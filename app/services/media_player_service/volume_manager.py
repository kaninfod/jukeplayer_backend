import logging
import asyncio

logger = logging.getLogger(__name__)

class VolumeManager:
    def __init__(self, playback_backend):
        self.playback_backend = playback_backend
        self._volume = 50  # Default volume level (0-100)
        self.is_muted = False

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.sync_volume_from_backend())
        except RuntimeError:
            asyncio.run(self.sync_volume_from_backend())

    @property
    def volume(self) -> int:
        return self._volume

    async def volume_up(self, step=5):
        new_volume = min(100, self._volume + step if step is not None else 0)
        await self.set_volume(new_volume)

    async def volume_down(self, step=5):
        new_volume = max(0, self._volume - step if step is not None else 0)
        await self.set_volume(new_volume)


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
                logger.info(f"Volume {'muted' if new_muted else 'unmuted'}")
                return {"success": True, "muted": new_muted}
            else:
                return {"success": False, "muted": current_muted}
        except Exception as e:
            logger.error(f"Failed to toggle mute: {e}")
            return {"success": False, "muted": None}
        
    async def sync_volume_from_backend(self):
        """Sync volume from active playback backend (0.0-1.0) to 0-100 scale."""
        backend_volume = await self.playback_backend.get_volume()
        logger.debug(f"[sync_volume_from_backend] volume from backend: {backend_volume}")
        
        value = int(backend_volume * 100) if backend_volume is not None else self._volume
        await self.set_volume(value)

        return self._volume        