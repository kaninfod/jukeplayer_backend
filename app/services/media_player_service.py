
from importlib.metadata import metadata
import time
import logging
from typing import List, Dict, Optional
from app.playback_backends.factory import get_playback_backend
from app.playback_backends.factory import get_playback_backend_by_name
from app.core import EventType, Event
from app.core import PlayerStatus

logger = logging.getLogger(__name__)

class MediaPlayerService:

    def __init__(self, playlist: List[Dict], event_bus, playback_backend=None):
        """
        Initialize MediaPlayerService with dependency injection.
        
        Args:
            playlist: List of tracks to play
            event_bus: EventBus instance for event communication
            playback_backend: Preferred backend implementation (chromecast/mpv)
        """
        self.playlist = playlist
        self.current_index = 0
        self.status = PlayerStatus.STOP
        self.active_client = None
        
        self.event_bus = event_bus
        if playback_backend:
            self.playback_backend = playback_backend
        else:
            self.playback_backend = get_playback_backend()

        self._repeat_album = False            
        self.current_volume = 25
        self.track_timer = TrackTimer()
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            loop.create_task(self.sync_volume_from_backend())
        except RuntimeError:
            asyncio.run(self.sync_volume_from_backend())
        
        logger.info(
            "MediaPlayerService initialized with playback backend=%s, device=%s",
            type(self.playback_backend).__name__,
            getattr(self.playback_backend, "device_name", "unknown"),
        )



    @property
    def album_cover(self) -> Optional[str]:
        track = self.current_track
        return track.get('album_cover_filename') if track else None

    @property
    def track_number(self) -> Optional[int]:
        track = self.current_track
        return track.get('track_number') if track else None

    @property
    def year(self) -> Optional[str]:
        track = self.current_track
        return track.get('year') if track else None

    @property
    def track_id(self) -> Optional[str]:
        track = self.current_track
        return track.get('track_id') if track else None
    
    @property
    def current_track(self) -> Optional[Dict]:
        if not self.playlist:
            return None
        return self.playlist[self.current_index]

    @property
    def artist(self) -> Optional[str]:
        track = self.current_track
        return track.get('artist') if track else None
    
    @property
    def title(self) -> Optional[str]:
        track = self.current_track
        return track.get('title') if track else None

    @property
    def duration(self) -> Optional[str]:
        track = self.current_track
        return track.get('duration') if track else None

    @property
    def thumb(self) -> Optional[str]:
        track = self.current_track
        return track.get('thumb') if track else None

    @property
    def cc_cover_url(self) -> Optional[str]:
        track = self.current_track
        return track.get('cc_cover_url') if track else None

    @property
    def album(self) -> Optional[str]:
        track = self.current_track
        return track.get('album') if track else None

    @property
    def volume(self) -> int:
        """Return the current volume (0-100)."""
        return self.current_volume

    @property
    def repeat_album(self) -> bool:
        """Return whether repeat album is enabled."""
        return self._repeat_album

    async def sync_volume_from_backend(self):
        """Sync volume from active playback backend (0.0-1.0) to 0-100 scale."""
        backend_volume = await self.playback_backend.get_volume()
        logger.debug(f"[sync_volume_from_backend] volume from backend: {backend_volume}")
        
        value = int(backend_volume * 100) if backend_volume is not None else self.current_volume
        self.current_volume = value
        # Use injected event_bus instead of importing
        self.event_bus.emit(Event(
            type=EventType.VOLUME_CHANGED,
            payload=self.get_context()
        ))
        return self.current_volume

    async def toggle_repeat_album(self, event=None):
        """Toggle repeat album setting."""
        self._repeat_album = not self._repeat_album
        logger.info(f"Repeat album set to: {self._repeat_album}")
        self.emit_update()
        return self._repeat_album

    async def play(self, event=None):
        """Start playback of the current track (cast and set state)."""

        if self.status == PlayerStatus.PLAY:
            self.track_timer.pause()
            self.status = PlayerStatus.PAUSE
            await self.playback_backend.pause()
            status = self.status
        elif self.status == PlayerStatus.PAUSE:
            self.track_timer.resume()
            self.status = PlayerStatus.PLAY
            await self.playback_backend.resume()
            status = self.status
        elif self.status == PlayerStatus.STOP:
            if len(self.playlist) > 0:
                self.current_index = 0  # Reset to start if at end of playlist
                self.status = PlayerStatus.PLAY
                await self.play_current_track()
                status = self.status
            else:
                logging.warning("No playlist loaded.")
                status = False
        
        self.emit_update()

        return status


    async def play_pause(self, event=None):
        # Toggle pause/resume timer based on current status
        if self.status == PlayerStatus.PLAY:
            self.track_timer.pause()
            self.status = PlayerStatus.PAUSE
            await self.playback_backend.pause()
        elif self.status == PlayerStatus.PAUSE:
            self.track_timer.resume()
            self.status = PlayerStatus.PLAY
            await self.playback_backend.resume()

        self.emit_update()
        return True

    async def stop(self, event=None):
        await self.playback_backend.stop()
        self.status = PlayerStatus.STOP
        self.current_index = 0  # Reset to start of playlist
        self.track_timer.reset()

        self.playlist = []  
        self.emit_update()                
        return True

    async def previous_track(self, event=None):
        if self.current_index > 0:
            self.current_index -= 1
            await self.play_current_track()
            return True

    async def next_track(self, event=None, force=False):
        if self.current_index < len(self.playlist) - 1:
            self.current_index += 1
            await self.play_current_track()
            return True
        elif self.repeat_album:
            self.current_index = 0
            await self.play_current_track()
            return True
        else:
            await self.stop()
            #self.playlist = []  # Clear playlist at end
            return False

    async def play_track(self, event=None):
        """Play a specific track by index from the event payload."""
        if event is None or not hasattr(event, "payload"):
            logger.error("play_track called without valid event payload.")
            return False
        
        track_index = event.payload.get("track_index")
        if track_index is None or not isinstance(track_index, int):
            logger.error(f"play_track: Invalid track_index in payload: {track_index}")
            return False
        
        if 0 <= track_index < len(self.playlist):
            self.current_index = track_index
            await self.play_current_track()
            return track_index
        else:
            logger.error(f"play_track: track_index {track_index} out of bounds (playlist size: {len(self.playlist)})")
            return False

    async def set_volume(self, volume=None, event=None):
        """Set volume (0-100) and sync with playback backend.

        Supports two invocation styles:
        - Direct call with numeric volume (used by volume_up/down)
        - EventBus call where the first argument is an Event carrying payload{"volume": X}
        """
        # Normalize input volume from either direct call or event payload
        requested = None
        # Check if first argument is an Event object (EventBus call)
        if hasattr(volume, "payload"):
            requested = volume.payload.get("volume")
        elif event is not None and hasattr(event, "payload"):
            requested = event.payload.get("volume")
        elif volume is not None and isinstance(volume, (int, float)) and volume >= 0:
            requested = volume

        try:
            self.current_volume = max(0, min(100, int(requested)))
        except Exception as e:
            logger.error(f"[set_volume] Failed to set current_volume from volume={requested}: {e}")
            self.current_volume = 0
        
        # Convert to Chromecast's 0.0-1.0 scale
        normalized_volume = self.current_volume / 100.0 if self.current_volume is not None else None

        if normalized_volume is not None:
            await self.playback_backend.set_volume(normalized_volume)

        logger.debug(f"[set_volume] current_volume set to: {self.current_volume}")
        self.event_bus.emit(Event(
            type=EventType.VOLUME_CHANGED,
            payload=self.get_context()
        ))
        
        return normalized_volume

    async def volume_up(self, event=None):
        await self.set_volume(self.current_volume + 5)
        return True


    async def volume_down(self, event=None):
        await self.set_volume(self.current_volume - 5)
        return True

    async def volume_mute(self, event=None):
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
                self.event_bus.emit(Event(
                    type=EventType.VOLUME_CHANGED,
                    payload=self.get_context()
                ))
                return {"success": True, "muted": new_muted}
            else:
                return {"success": False, "muted": current_muted}
        except Exception as e:
            logger.error(f"Failed to toggle mute: {e}")
            return {"success": False, "muted": None}

    async def play_current_track(self):
        track = self.playlist[self.current_index]
        await self.sync_volume_from_backend()
        if track['stream_url']:
            played_ok = await self.playback_backend.play_media(
                track['stream_url'], 
                media_info={
                    "title": track.get("title"),
                    "thumb": track.get('cc_cover_url'),
                    "media_info": {
                        "artist": track.get("artist"),
                        "album": track.get("album"),
                        "year": track.get("year"),
                    },
                    "metadata": {
                        "metadataType": 3,
                        "albumName": track.get("album"),
                        "artist": track.get("artist")
                    }
                }
            )
            if not played_ok:
                logger.error(
                    "Backend failed to start playback for track %s/%s: %s",
                    self.current_index + 1,
                    len(self.playlist),
                    track.get('title'),
                )
                self.status = PlayerStatus.STOP
                self.track_timer.reset()
                self.emit_update()
                return

            self.track_timer.reset()
            self.track_timer.start()
            self.status = PlayerStatus.PLAY
            
            # Scrobble to Subsonic/Last.fm now that track is playing
            track_id = track.get('track_id')
            if track_id:
                self._scrobble_track_now_playing(track_id, track.get('title'))
            
            self.emit_update()
            logger.info(f"Playing track {self.current_index+1}/{len(self.playlist)}: {track.get('title')}")
        else:
            logger.error("No stream_url for current track.")
    
    def _scrobble_track_now_playing(self, track_id: str, track_title: str = "Unknown") -> None:
        """
        Notify Subsonic that a track is now playing (scrobble to Last.fm if configured).
        
        This is called when playback starts and sends a scrobble
        notification to Subsonic, which forwards it to Last.fm if configured.
        
        Args:
            track_id: The Subsonic track ID to scrobble
            track_title: The track title for logging purposes
        """
        try:
            from app.core.service_container import get_service
            subsonic_service = get_service("subsonic_service")
            
            if not subsonic_service:
                logger.warning(f"_scrobble_track_now_playing: SubsonicService not available, skipping scrobble for '{track_title}'")
                return
            
            # Scrobble the track (non-blocking, don't wait for response)
            success = subsonic_service.scrobble_now_playing(track_id)
            if success:
                logger.info(f"_scrobble_track_now_playing: Scrobbled '{track_title}' to Subsonic/Last.fm")
            else:
                logger.warning(f"_scrobble_track_now_playing: Failed to scrobble '{track_title}' (this is non-critical)")
                
        except Exception as e:
            logger.error(f"_scrobble_track_now_playing: Error scrobbling track '{track_title}': {e}")
            # Non-critical error - don't let scrobbling failures affect playback
    
    def emit_update(self):
        """Emit TRACK_CHANGED event with current context."""
        self.event_bus.emit(Event(
            type=EventType.TRACK_CHANGED,
            payload=self.get_context()
        ))
    
    def get_context(self):
        from app.config import config
        return {
            "current_track": {
                "artist": self.artist,
                "title": self.title,
                "duration": self.duration,
                "album": self.album,
                "year": self.year,
                "track_id": self.track_id,
                "track_number": self.track_number,
                "thumb": self.thumb,
                "thumb_abs": self.cc_cover_url
            },
            "status": self.status.value,
            "current_index": self.current_index,
            "repeat_album": self._repeat_album,
            "playlist": self.playlist,
            "volume": self.volume,
            "elapsed_time": self.track_timer.get_elapsed(),
            "output_device": self.playback_backend.device_name,
            "active_client": getattr(self, 'active_client', None),
            "playback_backend": type(self.playback_backend).__name__ # config.PLAYBACK_BACKEND
        }

    def get_status(self) -> Dict:
        return {
            'status': self.status.value,
            'current_index': self.current_index,
            'current_track': self.playlist[self.current_index] if self.playlist else None
        }
    
    def _emit_event(self, event_type, data=None):
        # Use injected event_bus instead of importing
        self.event_bus.emit(Event(type=event_type, payload=data))

    async def cleanup(self):
        logger.info("MediaPlayerService cleanup called")
        try:
            await self.playback_backend.cleanup()
        except Exception:
            pass

    async def switch_playback_backend(self, backend: str, device_name: Optional[str] = None) -> Dict:
        previous_backend = self.playback_backend
        previous_backend_name = type(previous_backend).__name__
        previous_device = getattr(previous_backend, "device_name", None)
        previous_status = self.status
        previous_track_index = self.current_index
        previous_track_id = self.track_id

        target_backend = (backend or "").strip().lower()
        if target_backend not in ("mpv", "chromecast", "streaming"):
            return {
                "status": "error",
                "code": "invalid_backend",
                "message": f"Unsupported backend '{backend}'",
                "rollback_applied": False,
                "previous_backend": previous_backend_name,
            }

        is_current_chromecast = "chromecast" in previous_backend_name.lower()
        is_current_streaming = "websocket" in previous_backend_name.lower() or "streaming" in previous_backend_name.lower()
        
        if is_current_chromecast:
            current_auth_backend = "chromecast"
        elif is_current_streaming:
            current_auth_backend = "streaming"
        else:
            current_auth_backend = "mpv"

        requested_device = (device_name or "").strip() or None

        # Fast no-op when backend and device are already active.
        if target_backend == current_auth_backend:
            if target_backend == "chromecast":
                if not requested_device or requested_device == previous_device:
                    return {
                        "status": "ok",
                        "backend": "chromecast",
                        "device_name": previous_device,
                        "resumed": previous_status == PlayerStatus.PLAY,
                        "track_index": previous_track_index,
                        "track_id": previous_track_id,
                        "rollback_applied": False,
                        "previous_backend": previous_backend_name,
                        "previous_device": previous_device,
                    }
            else:
                return {
                    "status": "ok",
                    "backend": target_backend,
                    "device_name": getattr(previous_backend, "device_name", None),
                    "resumed": previous_status == PlayerStatus.PLAY,
                    "track_index": previous_track_index,
                    "track_id": previous_track_id,
                    "rollback_applied": False,
                    "previous_backend": previous_backend_name,
                    "previous_device": previous_device,
                }

        # Same-backend Chromecast device switch must reconnect immediately.
        if target_backend == "chromecast" and is_current_chromecast and requested_device and requested_device != previous_device:
            # We defer to the universal cross-backend logic below
            logger.info("Preparing to switch identical Chromecast backends with different target models.")

        try:
            previous_muted_state = None
            try:
                previous_muted_state = await previous_backend.get_volume_muted()
            except Exception:
                previous_muted_state = None

            if previous_status in (PlayerStatus.PLAY, PlayerStatus.PAUSE):
                try:
                    await previous_backend.stop()
                except Exception:
                    pass
            
            if "chromecast" in previous_backend_name.lower() and (target_backend != "chromecast" or (requested_device and requested_device != previous_device)):
                try:
                    if hasattr(previous_backend, "disconnect"):
                        logger.info("Disconnecting from old Chromecast device: %s", previous_device)
                        previous_backend.disconnect()
                except Exception as dc_error:
                    logger.warning("Failed to cleanly disconnect from previous Chromecast: %s", dc_error)

            new_backend = get_playback_backend_by_name(target_backend, device_name=requested_device)
            self.playback_backend = new_backend

            backend_volume = self.current_volume / 100.0
            await self.playback_backend.set_volume(backend_volume)

            if previous_muted_state is not None:
                await self.playback_backend.set_volume_muted(bool(previous_muted_state))

            resumed = False
            if self.playlist and 0 <= self.current_index < len(self.playlist):
                if previous_status == PlayerStatus.PLAY:
                    await self.play_current_track()
                    resumed = self.status == PlayerStatus.PLAY
                elif previous_status == PlayerStatus.PAUSE:
                    await self.play_current_track()
                    await self.playback_backend.pause()
                    self.track_timer.pause()
                    self.status = PlayerStatus.PAUSE
                    self.emit_update()

            return {
                "status": "ok",
                "backend": target_backend,
                "device_name": getattr(self.playback_backend, "device_name", None),
                "resumed": resumed,
                "track_index": previous_track_index,
                "track_id": previous_track_id,
                "rollback_applied": False,
                "previous_backend": previous_backend_name,
                "previous_device": previous_device,
            }
        except Exception as e:
            logger.error("Failed to switch playback backend to %s: %s", target_backend, e)
            self.playback_backend = previous_backend

            rollback_applied = False
            try:
                if previous_status == PlayerStatus.PLAY and self.playlist and 0 <= self.current_index < len(self.playlist):
                    await self.play_current_track()
                    rollback_applied = self.status == PlayerStatus.PLAY
                elif previous_status == PlayerStatus.PAUSE and self.playlist and 0 <= self.current_index < len(self.playlist):
                    await self.play_current_track()
                    await self.playback_backend.pause()
                    self.track_timer.pause()
                    self.status = PlayerStatus.PAUSE
                    self.emit_update()
                    rollback_applied = True
            except Exception:
                rollback_applied = False

            return {
                "status": "error",
                "code": "switch_failed",
                "message": str(e),
                "rollback_applied": rollback_applied,
                "previous_backend": previous_backend_name,
                "previous_device": previous_device,
            }

    def get_track_elapsed(self):
        """Return the elapsed play time (seconds) for the current track."""
        return self.track_timer.get_elapsed()


class TrackTimer:
    def __init__(self):
        self.start_time = None
        self.paused_time = 0
        self.is_paused = False
        self.pause_start = None

    def start(self):
        self.start_time = time.monotonic()
        self.paused_time = 0
        self.is_paused = False
        self.pause_start = None

    def pause(self):
        if not self.is_paused and self.start_time is not None:
            self.is_paused = True
            self.pause_start = time.monotonic()

    def resume(self):
        if self.is_paused and self.pause_start is not None:
            self.paused_time += time.monotonic() - self.pause_start
            self.is_paused = False
            self.pause_start = None

    def reset(self):
        self.__init__()

    def get_elapsed(self):
        if self.start_time is None:
            return 0
        if self.is_paused:
            return self.pause_start - self.start_time - self.paused_time
        else:
            return time.monotonic() - self.start_time - self.paused_time
