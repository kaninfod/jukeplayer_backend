import pytest
from unittest.mock import MagicMock, AsyncMock
from app.services.media_player_service.media_player_service import MediaPlayerService


def test_constructor_initializes_correctly(media_player_service, mock_event_bus, mock_playback_backend):
	assert media_player_service.event_bus == mock_event_bus
	assert media_player_service.playback_backend == mock_playback_backend
	assert media_player_service.status.value == "idle"

@pytest.mark.asyncio
async def test_toggle_repeat(media_player_service):
	initial = media_player_service.playlist_manager._repeat_album
	result = await media_player_service.toggle_repeat()
	assert result != initial

@pytest.mark.asyncio
async def test_play_pause(media_player_service):
	# Set status to PLAY, test pause
	media_player_service.status = media_player_service.status.PLAY
	await media_player_service.play_pause()
	assert media_player_service.status.value == "paused"
	# Set status to PAUSE, test resume
	media_player_service.status = media_player_service.status.PAUSE
	await media_player_service.play_pause()
	assert media_player_service.status.value == "playing"

@pytest.mark.asyncio
async def test_stop(media_player_service):
	media_player_service.status = media_player_service.status.PLAY
	result = await media_player_service.stop()
	assert result is True
	assert media_player_service.status.value == "idle"

@pytest.mark.asyncio
async def test_volume_up(media_player_service, mock_playback_backend):
    result = await media_player_service.handle_volume_up()
    assert result > 0
    
    mock_playback_backend.set_volume.assert_called()
	
def test_get_context_minimal(media_player_service):
	ctx = media_player_service.get_context(minimal=True)
	assert "current_track" in ctx
	assert "status" in ctx
	assert "volume" in ctx
	assert "repeat_album" in ctx
