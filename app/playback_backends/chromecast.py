"""
ChromecastService: On-demand Chromecast service for device discovery, connection, and media control.
Refactored from PyChromecastServiceOnDemand.
"""

import pychromecast
from pychromecast.controllers.media import MediaController
from zeroconf import Zeroconf
from typing import Optional, List, Dict
import logging
import time
from app.config import config
from .base import PlaybackBackend

logger = logging.getLogger(__name__)


DEFAULT_MEDIA_RECEIVER_APP_ID = "CC1AD845"

class ChromecastMediaStatusListener:
    """
    Listener for Chromecast media status changes.
    Provides detailed logging of all status changes for debugging and integration.
    """
    def __init__(self, device_name: str):
        self.device_name = device_name
        self.last_player_state = None
        self.last_current_time = None
    def new_media_status(self, status):
        try:
            player_state = getattr(status, 'player_state', 'UNKNOWN')
            current_time = getattr(status, 'current_time', 0)
            duration = getattr(status, 'duration', None)
            idle_reason = getattr(status, 'idle_reason', None)
            content_id = getattr(status, 'content_id', None)
            if player_state != self.last_player_state:
                logger.info(f"[{self.device_name}] Media state changed: {self.last_player_state} → {player_state}")
                self._log_full_status(status)
                if player_state == 'IDLE':
                    if idle_reason:
                        logger.info(f"[{self.device_name}] IDLE reason: {idle_reason}")
                    if idle_reason == 'FINISHED':
                        from app.core import event_bus, EventType, Event
                        event_bus.emit(Event(
                            type=EventType.TRACK_FINISHED,
                            payload={"Reason": idle_reason}
                        ))
                        logger.info(f"[{self.device_name}] 🎵 TRACK FINISHED - Duration: {duration}s, Position: {current_time}s")
                elif player_state == 'PLAYING':
                    logger.info(f"[{self.device_name}] ▶️  Started playing - Duration: {duration}s")
                elif player_state == 'PAUSED':
                    logger.info(f"[{self.device_name}] ⏸️  Paused at {current_time}s")
                elif player_state == 'BUFFERING':
                    logger.info(f"[{self.device_name}] ⏳ Buffering at {current_time}s")
                self.last_player_state = player_state
            if (player_state == 'PLAYING' and duration and 
                current_time and self.last_current_time and
                int(current_time / 10) != int(self.last_current_time / 10)):
                progress_pct = (current_time / duration) * 100 if duration > 0 else 0
                logger.debug(f"[{self.device_name}] Progress: {current_time:.1f}s / {duration:.1f}s ({progress_pct:.1f}%)")
            self.last_current_time = current_time
        except Exception as e:
            logger.error(f"[{self.device_name}] Error processing media status: {e}")
    
    def load_media_failed(self, item, error_code):
        """Called when media fails to load on the Chromecast device.
        
        This is a required callback for pychromecast v12.0.0+
        
        Args:
            item: The media item that failed to load
            error_code: Error code from the Chromecast device
        """
        try:
            logger.warning(f"[{self.device_name}] Media load failed: error_code={error_code}, item={item}")
        except Exception as e:
            logger.error(f"[{self.device_name}] Error in load_media_failed callback: {e}")
    
    def _log_full_status(self, status):
        try:
            logger.info(f"[{self.device_name}] 📊 FULL STATUS DUMP:")
            logger.info(f"  🎵 Playback: state={getattr(status, 'player_state', 'N/A')}, "
                       f"time={getattr(status, 'current_time', 'N/A')}s, "
                       f"duration={getattr(status, 'duration', 'N/A')}s")
            logger.info(f"  📀 Media: content_id={getattr(status, 'content_id', 'N/A')}, "
                       f"content_type={getattr(status, 'content_type', 'N/A')}")
            logger.info(f"  📝 Metadata: title='{getattr(status, 'title', 'N/A')}', "
                       f"artist='{getattr(status, 'artist', 'N/A')}', "
                       f"album='{getattr(status, 'album_name', 'N/A')}'")
            logger.info(f"  🔗 Session: id={getattr(status, 'media_session_id', 'N/A')}, "
                       f"stream_type={getattr(status, 'stream_type', 'N/A')}")
            supports = []
            if getattr(status, 'supports_pause', False): supports.append('pause')
            if getattr(status, 'supports_seek', False): supports.append('seek')
            if getattr(status, 'supports_stream_volume', False): supports.append('volume')
            if getattr(status, 'supports_skip_forward', False): supports.append('skip_forward')
            if getattr(status, 'supports_skip_backward', False): supports.append('skip_backward')
            logger.info(f"  🎛️  Supports: {', '.join(supports) if supports else 'none'}")
            logger.info(f"  🔊 Volume: level={getattr(status, 'volume_level', 'N/A')}, "
                       f"muted={getattr(status, 'volume_muted', 'N/A')}")
            idle_reason = getattr(status, 'idle_reason', None)
            playback_rate = getattr(status, 'playback_rate', None)
            images = getattr(status, 'images', [])
            logger.info(f"  ℹ️  Other: idle_reason={idle_reason}, "
                       f"playback_rate={playback_rate}, "
                       f"images_count={len(images) if images else 0}")
        except Exception as e:
            logger.error(f"[{self.device_name}] Error logging full status: {e}")

from pychromecast.discovery import CastBrowser, SimpleCastListener

# Move DiscoveryListener to module level
class DiscoveryListener(SimpleCastListener):
    def add_cast(self, uuid, mdns_name):
        pass

_global_zeroconf = None
_global_browser = None

def _get_global_browser():
    global _global_zeroconf, _global_browser
    if _global_zeroconf is None:
        _global_zeroconf = Zeroconf()
        _global_browser = CastBrowser(DiscoveryListener(), _global_zeroconf)
        _global_browser.start_discovery()
        logger.info("Started global background Chromecast discovery")
    return _global_browser

class ChromecastService(PlaybackBackend):
    """
    Simplified Chromecast service using persistent global discovery.
    """
    def __init__(self, device_name: Optional[str] = None):
        import threading
        self.device_name = device_name
        self.cast = None
        self.mc = None
        self.status_listener = None
        self._connection_lock = threading.Lock()
        
        # Start global discovery proactively
        _get_global_browser()

    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Don't disconnect or cleanup zeroconf when using context manager
        pass

    def _cleanup_zeroconf(self):
        # Global discovery never cleans up on individual backend teardown
        pass

    def list_chromecasts(self) -> List[Dict[str, str]]:
        """
        Return the configured list of Chromecast devices from config.
        No network scanning required - devices are statically configured.
        """
        devices = []
        for device_name in config.CHROMECAST_DEVICES:
            devices.append({
                'name': device_name,
                'model': 'Unknown',
                'host': 'Unknown',
                'uuid': 'Unknown'
            })
        logger.debug(f"Returning {len(devices)} configured Chromecast devices")
        return devices
    
    def scan_network_for_devices(self, timeout: Optional[int] = None) -> List[Dict[str, str]]:
        """
        Scan the network for available Chromecast devices.
        
        This performs a full network discovery and returns actual device information
        from the network. Useful for troubleshooting and verification.
        
        Args:
            timeout: Discovery timeout in seconds (defaults to CHROMECAST_DISCOVERY_TIMEOUT from config)
            
        Returns:
            List of discovered devices with full details:
            [
                {
                    'name': 'Living Room',
                    'model': 'Nest Audio',
                    'host': '192.168.68.46',
                    'uuid': 'uuid-string'
                },
                ...
            ]
        """
        devices, _, _ = self._discover_chromecasts(timeout=timeout)
        return devices
    
    def get_available_devices(self) -> List[str]:
        """
        Get list of available Chromecast device names from config.
        Useful for UI dropdowns and device selection.
        
        Returns:
            List of configured device names
        """
        return config.CHROMECAST_DEVICES

    def _discover_chromecasts(self, timeout=None, target_name=None):
        """
        Discover Chromecasts on the network using a persistent background browser.
        Returns (devices, target_cast_info, name_to_cast_info)
        """
        browser = _get_global_browser()
        devices = []
        target_cast_info = None
        name_to_cast_info = {}

        # Allow brief sync window if services are absolutely totally empty (likely just booted)
        if not browser.services:
            import time
            time.sleep(timeout or 1.0)

        for uuid, cast_info in browser.services.items():
            if hasattr(cast_info, 'friendly_name'):
                name = cast_info.friendly_name
                devices.append({
                    'name': name,
                    'model': getattr(cast_info, 'model_name', 'Unknown'),
                    'host': getattr(cast_info, 'host', 'Unknown'),
                    'uuid': str(uuid)
                })
                name_to_cast_info[name] = cast_info
                if target_name and name == target_name:
                    target_cast_info = cast_info

        logger.debug(f"Background discovery scan complete: found {len(devices)} Chromecast devices")
        return devices, target_cast_info, name_to_cast_info

    def connect(self, device_name: Optional[str] = None, fallback: bool = True) -> bool:
        """
        Connect to a Chromecast device from the statically configured device list.
        
        If the target device is unavailable and fallback=True, tries fallback devices
        in priority order from CHROMECAST_FALLBACK_DEVICES config.
        
        Args:
            device_name: Target device name (must be in CHROMECAST_DEVICES config)
            fallback: If True, try fallback devices if target is unavailable
            
        Returns:
            True if connected successfully, False otherwise
        """
        target_name = device_name or self.device_name
        if self.cast:
            self.disconnect()
        
        logger.info(f"Attempting to connect to Chromecast: {target_name}")
        
        # Determine device list to try (target first, then fallbacks)
        devices_to_try = [target_name]
        if fallback:
            devices_to_try.extend(config.CHROMECAST_FALLBACK_DEVICES)
        
        # Try each device in order
        for attempt_device in devices_to_try:
            if attempt_device not in config.CHROMECAST_DEVICES:
                logger.warning(f"Device '{attempt_device}' not in configured devices list, skipping")
                continue
            
            try:
                logger.info(f"Trying to connect to {attempt_device}...")
                # Discover only the target device on the network
                devices, target_cast_info, _ = self._discover_chromecasts(target_name=attempt_device)
                
                if not target_cast_info:
                    logger.warning(f"Device '{attempt_device}' not found on network")
                    if attempt_device == target_name and fallback:
                        logger.info(f"Primary device unavailable, trying fallback devices...")
                    continue
                
                # Found the device, establish connection
                self.cast = pychromecast.get_chromecast_from_cast_info(
                    target_cast_info, _global_zeroconf
                )
                logger.info(f"Waiting for {self.cast.name} to be ready...")
                self.cast.wait(timeout=config.CHROMECAST_WAIT_TIMEOUT)
                if not self.cast.status:
                    raise Exception("Device status not available after connection")
                
                self.mc = self.cast.media_controller
                self.status_listener = ChromecastMediaStatusListener(self.cast.name)
                self.mc.register_status_listener(self.status_listener)
                self.device_name = self.cast.name
                logger.info(f"Registered media status listener for {self.cast.name}")
                logger.info(f"Successfully connected to {self.cast.name}")
                logger.debug(f"Device status: {self.cast.status}")
                return True
                
            except Exception as e:
                logger.warning(f"Failed to connect to {attempt_device}: {e}")
                self.disconnect()
                if attempt_device == target_name and fallback:
                    logger.info(f"Primary device failed, trying fallback devices...")
                continue
        
        logger.error(f"Failed to connect to any device (tried: {', '.join(devices_to_try)})")
        return False
                
    def disconnect(self):
        if self.cast:
            try:
                logger.info(f"Disconnecting from {self.cast.name}")
                if self.mc and self.status_listener:
                    try:
                        if hasattr(self.mc, 'unregister_status_listener'):
                            self.mc.unregister_status_listener(self.status_listener)
                            logger.debug("Unregistered media status listener")
                        else:
                            if hasattr(self.mc, 'remove_status_listener'):
                                self.mc.remove_status_listener(self.status_listener)
                                logger.debug("Removed media status listener")
                            else:
                                logger.debug("No status listener removal method found")
                    except Exception as e:
                        logger.warning(f"Error unregistering status listener: {e}")
                self.cast.disconnect()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self.cast = None
                self.mc = None
                self.status_listener = None


    def is_connected(self) -> bool:
        if not self.cast or not self.mc:
            return False
        try:
            return self.cast.status is not None
        except Exception:
            return False
        
    def ensure_connected(self) -> bool:
        if self.is_connected():
            return True
            
        with self._connection_lock:
            # Recheck after acquiring lock in case another thread just connected
            if self.is_connected():
                return True
                
            logger.info("Connection lost, attempting to reconnect...")
            return self.connect()

    def _is_cast_group(self) -> bool:
        """Best-effort detection of cast groups.

        We avoid force-taking over groups by default because they can have
        different semantics and can impact multiple devices.
        """
        try:
            cast_info = getattr(self.cast, "cast_info", None)
            cast_type = getattr(cast_info, "cast_type", None)
            if cast_type is None:
                cast_type = getattr(self.cast, "cast_type", None)
            return str(cast_type).lower() == "group"
        except Exception:
            return False

    def _force_takeover_receiver_app_if_needed(self) -> None:
        """Force the Chromecast to exit any active non-media receiver app.

        This is intentionally aggressive: it will interrupt other senders.
        """
        if not self.cast or not getattr(self.cast, "status", None):
            return

        if self._is_cast_group():
            logger.info(
                "Skipping force takeover on cast group device: %s",
                getattr(self.cast, "name", "unknown"),
            )
            return

        app_id = getattr(self.cast.status, "app_id", None)
        display_name = getattr(self.cast.status, "display_name", None)

        # If no app_id is reported, the device is likely idle/backdrop.
        if not app_id:
            return

        # Default Media Receiver is what we want for direct URL playback.
        if app_id == DEFAULT_MEDIA_RECEIVER_APP_ID:
            return

        logger.warning(
            "Force-taking over Chromecast '%s': quitting active app '%s' (app_id=%s)",
            getattr(self.cast, "name", "unknown"),
            display_name or "unknown",
            app_id,
        )
        try:
            # This will stop the current receiver app (e.g. YouTube Music).
            self.cast.quit_app()
        except Exception as e:
            logger.warning("Failed to quit active Chromecast app (app_id=%s): %s", app_id, e)

        # Give the device a moment to settle before we send LOAD.
        time.sleep(0.8)
    
    def _do_play_media(self, url: str, media_info: dict = None, content_type: str = "audio/mp3") -> bool:
        try:
            # Aggressive takeover: if another sender has YouTube/Spotify/etc active,
            # quit that receiver app before attempting playback.
            self._force_takeover_receiver_app_if_needed()

            logger.info(f"Playing media on {self.cast.name}: {url} with {media_info}")
            if media_info:
                title = media_info.get("title", "Unknown Title")
                thumb = media_info.get("thumb")
                nested_info = media_info.get("media_info", {})
                artist = nested_info.get("artist") or media_info.get("artist", "Unknown Artist")
                album = nested_info.get("album") or media_info.get("album", "Unknown Album")
                year = nested_info.get("year") or media_info.get("year")
                metadata_dict = media_info.get("metadata", {})
                metadata = {
                    "metadataType": metadata_dict.get("metadataType", 3),
                    "title": title,
                    "artist": artist,
                    "albumName": album,
                }
                if year:
                    metadata["releaseDate"] = str(year)
                if thumb:
                    metadata["images"] = [{"url": thumb}]
                logger.info(f"Playing with metadata: {title} by {artist} from {album}")
                logger.debug(f"Metadata being sent: {metadata}")
                self.mc.play_media(url, content_type, title=title, thumb=thumb, metadata=metadata)
            else:
                logger.info("Playing media without metadata")
                self.mc.play_media(url, content_type)
            self.mc.block_until_active(timeout=config.CHROMECAST_WAIT_TIMEOUT)
            logger.info("Media started successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to play media: {e}")
            import pychromecast.error
            if not media_info or isinstance(e, (pychromecast.error.PyChromecastError, OSError, TimeoutError)):
                return False
                
            try:
                logger.info("Attempting fallback playback without metadata")
                self._force_takeover_receiver_app_if_needed()
                self.mc.play_media(url, content_type)
                self.mc.block_until_active(timeout=config.CHROMECAST_WAIT_TIMEOUT)
                return True
            except Exception as fallback_e:
                logger.error(f"Fallback playback also failed: {fallback_e}")
                return False

    async def play_media(self, url: str, media_info: dict = None, content_type: str = "audio/mp3") -> bool:
        import asyncio
        if not await asyncio.to_thread(self.ensure_connected):
            logger.error("Cannot play media: no Chromecast connection")
            return False
            
        return await asyncio.to_thread(self._do_play_media, url, media_info, content_type)
    async def pause(self) -> bool:
        import asyncio
        if not await asyncio.to_thread(self.ensure_connected):
            return False
        try:
            await asyncio.to_thread(self.mc.pause)
            logger.info("Media paused")
            return True
        except Exception as e:
            logger.error(f"Failed to pause: {e}")
            return False
    async def resume(self) -> bool:
        import asyncio
        if not await asyncio.to_thread(self.ensure_connected):
            return False
        try:
            await asyncio.to_thread(self.mc.play)
            logger.info("Media resumed")
            return True
        except Exception as e:
            logger.error(f"Failed to resume: {e}")
            return False
    async def stop(self) -> bool:
        import asyncio
        if not await asyncio.to_thread(self.ensure_connected):
            return False
        try:
            await asyncio.to_thread(self.mc.stop)
            logger.info("Media stopped")
            return True
        except Exception as e:
            logger.error(f"Failed to stop: {e}")
            return False
    async def set_volume(self, volume: float) -> bool:
        import asyncio
        if not await asyncio.to_thread(self.ensure_connected):
            return False
        try:
            volume = max(0.0, min(1.0, volume))
            await asyncio.to_thread(self.cast.set_volume, volume)
            logger.info(f"Volume set to {volume:.1%}")
            return True
        except Exception as e:
            logger.error(f"Failed to set volume: {e}")
            return False
    
    async def set_volume_muted(self, muted: bool) -> bool:
        """Mute or unmute the Chromecast device.
        
        Args:
            muted: True to mute, False to unmute
        Returns:
            True if successful, False otherwise
        """
        import asyncio
        if not await asyncio.to_thread(self.ensure_connected):
            return False
        try:
            await asyncio.to_thread(self.cast.set_volume_muted, muted)
            logger.info(f"Volume {'muted' if muted else 'unmuted'}")
            return True
        except Exception as e:
            logger.error(f"Failed to set mute: {e}")
            return False
    
    async def get_volume_muted(self) -> Optional[bool]:
        """Get the current mute state of the Chromecast device.
        
        Returns:
            True if muted, False if not muted, None if not connected
        """
        if not self.is_connected():
            return None
        try:
            muted = self.cast.status.volume_muted
            logger.debug(f"Volume muted: {muted}")
            return muted
        except Exception as e:
            logger.error(f"Failed to get mute status: {e}")
            return None
    
    async def get_volume(self) -> Optional[float]:
        if not self.is_connected():
            return None
        try:
            volume = self.cast.status.volume_level
            logger.debug(f"Current volume: {volume:.1%}")
            return volume
        except Exception as e:
            logger.error(f"Failed to get volume: {e}")
            return None
    async def get_status(self) -> Optional[Dict]:
        if not self.is_connected():
            return None
        try:
            status = {
                'device_name': self.cast.name,
                'volume_level': self.cast.status.volume_level,
                'volume_muted': self.cast.status.volume_muted,
                'is_active_input': getattr(self.cast.status, 'is_active_input', None),
                'is_stand_by': getattr(self.cast.status, 'is_stand_by', None),
                'app_id': self.cast.status.app_id,
                'display_name': self.cast.status.display_name,
                'status_text': self.cast.status.status_text,
            }
            if self.mc and self.mc.status:
                status.update({
                    'media_session_id': self.mc.status.media_session_id,
                    'player_state': self.mc.status.player_state,
                    'current_time': getattr(self.mc.status, 'current_time', None),
                    'duration': getattr(self.mc.status, 'duration', None),
                    'media_title': getattr(self.mc.status, 'title', None),
                    'media_artist': getattr(self.mc.status, 'artist', None),
                })
            return status
        except Exception as e:
            logger.error(f"Failed to get status: {e}")
            return None
        
    async def cleanup(self):
        import asyncio
        logger.info("Performing full cleanup of Chromecast service")
        await asyncio.to_thread(self.disconnect)
        self._cleanup_zeroconf()        

_service_instance = None
def get_chromecast_service(device_name: Optional[str] = None) -> ChromecastService:
    global _service_instance
    if _service_instance is None:
        _service_instance = ChromecastService(device_name)
        logger.info("Initialized persistent Chromecast service")
    if device_name and device_name != _service_instance.device_name:
        _service_instance.device_name = device_name
        logger.info(f"Updated target device to: {device_name}")
    return _service_instance
