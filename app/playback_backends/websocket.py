"""WebSocket streaming playback backend for ESP32 audio streaming."""

import logging
from typing import Dict, Optional
from app.playback_backends.base import PlaybackBackend

logger = logging.getLogger(__name__)


class WebSocketStreamingBackend(PlaybackBackend):
    """WebSocket streaming backend for pushing audio to ESP32 and WebSocket clients.
    
    This is a placeholder backend that implements the PlaybackBackend interface.
    Future phases will add actual binary audio streaming via WebSocket connections.
    """
    
    def __init__(self):
        """Initialize the WebSocket streaming backend."""
        self.device_name = "ESP32"
        self._current_url = None
        self._is_playing = False
        self._volume = 1.0
        self._muted = False
        logger.info("WebSocket streaming backend initialized")
    
    async def play_media(self, url: str, media_info: dict = None, 
                   content_type: str = "audio/mp3") -> bool:
        """Queue audio for playback over WebSocket.
        
        Args:
            url: URL or file path to stream
            media_info: Optional metadata (title, artist, album, etc.)
            content_type: MIME type of audio (default: audio/mp3)
        
        Returns:
            True if queued successfully, False otherwise
        """
        try:
            self._current_url = url
            self._is_playing = True
            
            if media_info:
                title = media_info.get("title", "Unknown")
                artist = media_info.get("artist", "Unknown")
                logger.info(f"WS Backend: queued {artist} - {title}")
            else:
                logger.info(f"WS Backend: queued {url}")
            
            return True
        except Exception as e:
            logger.error(f"WS Backend play_media error: {e}")
            return False
    
    async def pause(self) -> bool:
        """Pause audio streaming.
        
        Returns:
            True if paused successfully, False otherwise
        """
        try:
            self._is_playing = False
            logger.info("WS Backend: paused")
            return True
        except Exception as e:
            logger.error(f"WS Backend pause error: {e}")
            return False
    
    async def resume(self) -> bool:
        """Resume audio streaming.
        
        Returns:
            True if resumed successfully, False otherwise
        """
        try:
            self._is_playing = True
            logger.info("WS Backend: resumed")
            return True
        except Exception as e:
            logger.error(f"WS Backend resume error: {e}")
            return False
    
    async def stop(self) -> bool:
        """Stop audio streaming.
        
        Returns:
            True if stopped successfully, False otherwise
        """
        try:
            self._is_playing = False
            self._current_url = None
            logger.info("WS Backend: stopped")
            return True
        except Exception as e:
            logger.error(f"WS Backend stop error: {e}")
            return False
    
    async def set_volume(self, volume: float) -> bool:
        """Set volume level (0.0 = mute, 1.0 = max).
        
        Args:
            volume: Volume level 0.0-1.0
        
        Returns:
            True if set successfully, False otherwise
        """
        try:
            self._volume = max(0.0, min(1.0, volume))
            volume_percent = int(self._volume * 100)
            logger.info(f"WS Backend: volume set to {volume_percent}%")
            return True
        except Exception as e:
            logger.error(f"WS Backend set_volume error: {e}")
            return False
    
    async def get_volume(self) -> Optional[float]:
        """Get current volume level.
        
        Returns:
            Current volume (0.0-1.0) or None if unavailable
        """
        return self._volume
    
    async def set_volume_muted(self, muted: bool) -> bool:
        """Set mute state.
        
        Args:
            muted: True to mute, False to unmute
        
        Returns:
            True if set successfully, False otherwise
        """
        try:
            self._muted = bool(muted)
            state = "muted" if self._muted else "unmuted"
            logger.info(f"WS Backend: {state}")
            return True
        except Exception as e:
            logger.error(f"WS Backend set_volume_muted error: {e}")
            return False
    
    async def get_volume_muted(self) -> Optional[bool]:
        """Get current mute state.
        
        Returns:
            Current mute state or None if unavailable
        """
        return self._muted
    
    async def get_status(self) -> Optional[Dict]:
        """Get current playback status.
        
        Returns:
            Status dictionary or None if unavailable
        """
        try:
            return {
                "device_name": self.device_name,
                "player_state": "PLAYING" if self._is_playing else "PAUSED" if self._current_url else "IDLE",
                "volume_level": self._volume,
                "volume_muted": self._muted,
                "backend": "streaming",
                "current_url": self._current_url,
            }
        except Exception as e:
            logger.error(f"WS Backend get_status error: {e}")
            return None
    
    async def cleanup(self):
        """Clean up resources and shutdown.
        
        This is called when the backend is being shut down.
        """
        try:
            self._is_playing = False
            self._current_url = None
            logger.info("WS Backend: cleanup complete")
        except Exception as e:
            logger.error(f"WS Backend cleanup error: {e}")


# Singleton instance
_ws_backend_instance = None


def get_websocket_backend() -> WebSocketStreamingBackend:
    """Get or create the singleton WebSocket backend instance.
    
    Returns:
        The WebSocketStreamingBackend singleton
    """
    global _ws_backend_instance
    if _ws_backend_instance is None:
        _ws_backend_instance = WebSocketStreamingBackend()
    return _ws_backend_instance
