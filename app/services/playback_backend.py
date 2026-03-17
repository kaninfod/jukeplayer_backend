from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Optional


class PlaybackBackend(ABC):
    """Contract for playback backends used by MediaPlayerService."""

    device_name: str

    @abstractmethod
    def play_media(self, url: str, media_info: dict = None, content_type: str = "audio/mp3") -> bool:
        pass

    @abstractmethod
    def pause(self) -> bool:
        pass

    @abstractmethod
    def resume(self) -> bool:
        pass

    @abstractmethod
    def stop(self) -> bool:
        pass

    @abstractmethod
    def set_volume(self, volume: float) -> bool:
        """Set volume using normalized range 0.0..1.0."""
        pass

    @abstractmethod
    def get_volume(self) -> Optional[float]:
        """Get volume using normalized range 0.0..1.0."""
        pass

    @abstractmethod
    def set_volume_muted(self, muted: bool) -> bool:
        pass

    @abstractmethod
    def get_volume_muted(self) -> Optional[bool]:
        pass

    @abstractmethod
    def get_status(self) -> Optional[Dict]:
        pass

    @abstractmethod
    def cleanup(self):
        pass
