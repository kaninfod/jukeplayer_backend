"""MediaPlayerService package: player + playlist/volume helpers.

MediaPlayerService lives in service.py; the package re-exports everything
callers need so `from app.services.media_player_service import X` and
`from app.services import MediaPlayerService` both work.
"""
from .playlist_manager import PlaylistManager, PlaylistItem
from .volume_manager import VolumeManager
from .service import MediaPlayerService

__all__ = [
    "MediaPlayerService",
    "PlaylistManager",
    "PlaylistItem",
    "VolumeManager",
]