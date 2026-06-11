import pytest
from unittest.mock import AsyncMock, MagicMock
from jukeplayer_backend.app.services.media_player_service.DELETE_media_player_service import MediaPlayerService
from app.core import EventBus

@pytest.fixture
def mock_event_bus():
    return MagicMock(spec=EventBus)

@pytest.fixture
def mock_playback_backend():
    backend = MagicMock()
    backend.play_media = AsyncMock(return_value=True)
    backend.pause = AsyncMock(return_value=True)
    backend.resume = AsyncMock(return_value=True)
    backend.stop = AsyncMock(return_value=True)
    backend.set_volume = AsyncMock(return_value=True)
    backend.get_volume = AsyncMock(return_value=0.5)
    backend.set_volume_muted = AsyncMock(return_value=True)
    backend.get_volume_muted = AsyncMock(return_value=False)
    backend.get_status = AsyncMock(return_value={})
    backend.cleanup = AsyncMock(return_value=None)
    backend.device_name = "mock_device"
    return backend

@pytest.fixture
def media_player_service(mock_event_bus, mock_playback_backend):
    return MediaPlayerService(event_bus=mock_event_bus, playback_backend=mock_playback_backend)
