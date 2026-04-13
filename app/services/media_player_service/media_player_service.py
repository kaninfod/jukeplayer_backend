
from importlib.metadata import metadata
import time
import logging
from typing import List, Dict, Optional
from app.playback_backends.factory import get_playback_backend, get_playback_backend_by_name
#from app.playback_backends.factory import get_playback_backend_by_name
from app.core import EventType, Event
from app.core import PlayerStatus
from .playlist_mamager import PlaylistManager
from .volume_manager import VolumeManager

logger = logging.getLogger(__name__)

class MediaPlayerService:

    def __init__(self, event_bus, playback_backend=None):
        """
        Initialize MediaPlayerService with dependency injection.
        
        Args:
            playlist: List of tracks to play
            event_bus: EventBus instance for event communication
            playback_backend: Preferred backend implementation (chromecast/mpv)
        """
        self.playlist_manager = PlaylistManager("new_playlist")
        self.status = PlayerStatus.STOP
        self.active_client = None
        self.event_bus = event_bus
        
        
        if playback_backend:
            self.playback_backend = playback_backend
        else:
            self.playback_backend = get_playback_backend()

        self.volume_manager = VolumeManager(self.playback_backend)
        self.track_timer = TrackTimer()
        
        logger.info(
            "MediaPlayerService initialized with playback backend=%s, device=%s",
            type(self.playback_backend).__name__,
            getattr(self.playback_backend, "device_name", "unknown"),
        )

    async def toggle_repeat_album(self, event=None):
        """Toggle repeat album setting."""
        mode = self.playlist_manager.toggle_repeat()
        return mode
    
    async def previous_track(self, event=None):
        self.playlist_manager.previous_track()
        await self.play_current_track()
        return True

    async def next_track(self, event=None, force=False):
        state = self.playlist_manager.next_track()
        if state == False:
            await self.stop()
            return False
        else:
            await self.play_current_track()
            return True

    async def _on_volume_event(self, event):
        """The 'Adapter': Extracts data from the event bus."""
        volume = event.payload.get("volume")
        if volume is not None:
            await self.set_volume(volume)

    async def set_volume(self, volume=None):
        """Set volume (0-100) and sync with playback backend."""

        volume = await self.volume_manager.set_volume(volume)

        logger.debug(f"[set_volume] current_volume set to: {self.volume_manager.volume}")
        self.event_bus.emit(Event(
            type=EventType.VOLUME_CHANGED,
            payload=self.get_context()
        ))
        return volume

    async def handle_volume_up(self, event=None):
        await self.volume_manager.volume_up()
        return True

    async def handle_volume_down(self, event=None):
        await self.volume_manager.volume_down()
        return True

    async def handle_volume_mute(self, event=None):
        """Toggle mute on the active playback backend."""    
        await self.volume_manager.toggle_mute()

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
        self.playlist_manager.current_index = 0  # Reset to start of playlist
        self.track_timer.reset()

        self.playlist = []  
        self.emit_update()                
        return True    

    async def play_track(self, event=None):
        """Play a specific track by index from the event payload."""
        if event is None or not hasattr(event, "payload"):
            logger.error("play_track called without valid event payload.")
            return False
        
        track_index = event.payload.get("track_index")
        if track_index is None or not isinstance(track_index, int):
            logger.error(f"play_track: Invalid track_index in payload: {track_index}")
            return False
        
        if 0 <= track_index < self.playlist_manager.count():
            self.playlist_manager.current_index = track_index
            await self.play_current_track()
            return track_index
        else:
            logger.error(f"play_track: track_index {track_index} out of bounds (playlist size: {self.playlist_manager.count()})")
            return False

    async def play_current_track(self):
        track = self.playlist_manager.current_track
    
        if track and track.stream_url:
            played_ok = await self.playback_backend.play_media(
                track.stream_url, 
                media_info={
                    "title": track.title,
                    "thumb": track.cover_url,
                    "media_info": {
                        "artist": track.artist,
                        "album": track.album,
                        "year": track.year,
                    },
                    "metadata": {
                        "metadataType": 3,
                        "albumName": track.album,
                        "artist": track.artist
                    }
                }
            )
            if not played_ok:
                logger.error(
                    "Backend failed to start playback for track %s/%s: %s",
                    self.playlist_manager.current_index + 1,
                    self.playlist_manager.count(),
                    track.title,
                )

                self.status = PlayerStatus.STOP
                self.track_timer.reset()
                self.emit_update()
                return

            self.track_timer.reset()
            self.track_timer.start()
            self.status = PlayerStatus.PLAY
            
            track_id = track.track_id
            if track_id:
                self._scrobble_track_now_playing(track_id, track.title)
            
            self.emit_update()
            logger.info(f"Playing track {self.playlist_manager.current_index+1}/{self.playlist_manager.count()}: {track.title}")
        else:
            logger.error("No stream_url for current track.")
    
    def _scrobble_track_now_playing(self, track_id: str, track_title: str = "Unknown") -> None:
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
    
    def get_context(self, minimal: bool = False):
        """
        Return the current playback context.
        If minimal is True, only include minimal fields for current_track, status, current_index, and volume.
        """
        track = self.playlist_manager.current_track or None

        if minimal:
            return {
                "current_track": {
                    "artist": track.artist if track else None,
                    "title": track.title if track else None,
                    "album": track.album if track else None,
                    "track_id": track.track_id if track else None,
                    "track_number": track.track_number if track else None,
                    "cover_url": track.cover_url if track else None,
                },
                "status": self.status.value,
                "current_index": self.playlist_manager.current_index,
                "volume": self.volume_manager.volume,
            }
        else:
            context = {
                "current_track": {
                    "artist": track.artist if track else None,
                    "title": track.title if track else None,
                    "duration": track.duration if track else None,
                    "album": track.album if track else None,
                    "year": track.year if track else None,
                    "track_id":  track.track_id if track else None,
                    "track_number":  track.track_number if track else None,
                    "cover_url": track.cover_url if track else None
                },
                "status": self.status.value,
                "current_index": self.playlist_manager.current_index,
                "repeat_album": self.playlist_manager._repeat_album,
                "playlist": self.playlist_manager.to_dict() if self.playlist_manager else None,
                "volume": self.volume_manager.volume,
                "elapsed_time": self.track_timer.get_elapsed(),
                "output_device": self.playback_backend.device_name,
                "active_client": getattr(self, 'active_client', None),
                "playback_backend": type(self.playback_backend).__name__
            }
            return context
    
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
        from app.playback_backends.factory import switch_playback_backend_fac
        return await switch_playback_backend_fac(self, self, backend, device_name)

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
