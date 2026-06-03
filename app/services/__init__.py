# Services module for the jukebox application
# NOTE: MediaPlayerService is imported from the file at app/services/media_player_service.py
# NOT from the package directory app/services/media_player_service/
import importlib.util
import os

# Load MediaPlayerService from the file directly to avoid package ambiguity
_mps_file_path = os.path.join(os.path.dirname(__file__), 'media_player_service.py')
_spec = importlib.util.spec_from_file_location("_media_player_service_module", _mps_file_path)
_mps_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mps_module)
MediaPlayerService = _mps_module.MediaPlayerService

from .playback_service import PlaybackService
#from .media_player_service.playlist_mamager import PlaylistManager, PlaylistItem
#from .media_player_service.volume_manager import VolumeManager