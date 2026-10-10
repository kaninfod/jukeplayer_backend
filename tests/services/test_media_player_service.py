import pytest
from unittest.mock import MagicMock, AsyncMock
from app.services import MediaPlayerService


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
    assert result["message"] == "Volume increased"
    assert result["volume"] > 0

    mock_playback_backend.set_volume.assert_called()
	
def test_get_context_minimal(media_player_service):
	ctx = media_player_service.get_context(minimal=True)
	assert "current_track" in ctx
	assert "status" in ctx
	assert "volume" in ctx
	assert "repeat_album" in ctx


@pytest.mark.asyncio
async def test_play_pause_resume_refused_marks_stopped(media_player_service, mock_playback_backend):
    """The mpv backend refuses a resume when it had to tear down a dead
    output — the service must NOT keep claiming PLAY (the stale-PLAY bug
    after pulling a USB DAC); the next play starts a fresh output."""
    from app.core.player_status import PlayerStatus
    mock_playback_backend.resume = AsyncMock(return_value=False)
    media_player_service.status = PlayerStatus.PAUSE

    await media_player_service.play_pause()

    assert media_player_service.status == PlayerStatus.STOP
    mock_playback_backend.resume.assert_awaited_once()


@pytest.mark.asyncio
async def test_play_pause_resume_ok_sets_play(media_player_service):
    """Regression: an accepted resume still flips PAUSE → PLAY."""
    from app.core.player_status import PlayerStatus
    media_player_service.status = PlayerStatus.PAUSE

    await media_player_service.play_pause()

    assert media_player_service.status == PlayerStatus.PLAY


@pytest.mark.asyncio
async def test_start_refusal_raises_playback_error(media_player_service, mock_playback_backend, monkeypatch):
    """'You tried to play and the speaker was not ready' — the play-start
    refusal raises PLAYBACK_ERROR(source=start_refused) carrying the oracle's
    human reason. Raised only for now (no listening handler yet)."""
    from app.core import event_bus
    from app.core.event_factory import EventType
    from app.core.player_status import PlayerStatus
    from app.services.media_player_service.playlist_manager import PlaylistItem

    emitted = []
    monkeypatch.setattr(event_bus, "emit", lambda ev: emitted.append(ev))
    mock_playback_backend.play_media = AsyncMock(return_value=False)
    mock_playback_backend.device_name = "zd3"
    mock_playback_backend.get_output_readiness = (
        lambda: {"ready": False, "message": "Target card not present (unplugged?)"})
    media_player_service.playlist_manager.add_item(PlaylistItem(
        track_id="tr-1", stream_url="http://example/tr-1", duration="200",
        track_number=1, title="Song", artist="A", album="Al", year="2000",
        cover_url=""))
    media_player_service.status = PlayerStatus.PLAY

    await media_player_service.play_current_track()

    assert media_player_service.status == PlayerStatus.STOP
    assert [ev.type for ev in emitted] == [EventType.PLAYBACK_ERROR]
    assert emitted[0].payload["source"] == "start_refused"
    assert emitted[0].payload["message"] == "Target card not present (unplugged?)"
    assert emitted[0].payload["device_name"] == "zd3"
