import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.music_sources.subsonic import SubsonicSource
from app.playback.media_player_service.playlist_manager import PlaylistItem


def _item(duration="200", track_id="subsonic:tr-1"):
    return PlaylistItem(
        track_id=track_id,
        stream_url="http://example/stream",
        duration=duration,
        track_number=1,
        title="Song",
        artist="Artist",
        album="Album",
        year="2020",
        cover_url="/cover.jpg",
    )


def test_finish_submits_only_after_the_threshold(media_player_service):
    player = media_player_service
    player.playlist_manager.add_item(_item("200"))
    player.playlist_manager.current_index = 0
    player._track_started_at = time.time() - 120
    player.track_timer.get_elapsed = MagicMock(return_value=120)
    submitted = []
    player._scrobble_track_completed = lambda *args: submitted.append(args)

    assert player.finish_current_track("test") is True
    assert len(submitted) == 1
    assert submitted[0][0] == "subsonic:tr-1"
    # One-shot: a natural finish followed by stop() must not submit twice.
    assert player.finish_current_track("again") is False
    assert len(submitted) == 1


def test_finish_does_not_submit_an_early_skip(media_player_service):
    player = media_player_service
    player.playlist_manager.add_item(_item("200"))
    player.playlist_manager.current_index = 0
    player._track_started_at = time.time() - 10
    player.track_timer.get_elapsed = MagicMock(return_value=10)
    submitted = []
    player._scrobble_track_completed = lambda *args: submitted.append(args)

    assert player.finish_current_track("skip") is False
    assert submitted == []


@pytest.mark.asyncio
async def test_next_track_finishes_before_advancing(media_player_service):
    player = media_player_service
    player.playlist_manager.add_item(_item(track_id="subsonic:tr-1"))
    player.playlist_manager.add_item(_item(track_id="subsonic:tr-2"))
    player.playlist_manager.current_index = 0
    player.finish_current_track = MagicMock(return_value=True)
    player.play_current_track = AsyncMock()

    assert await player.next_track() is True
    player.finish_current_track.assert_called_once_with("next")
    assert player.playlist_manager.current_index == 1


@pytest.mark.asyncio
async def test_stop_finishes_the_current_track(media_player_service, mock_playback_backend):
    player = media_player_service
    player.finish_current_track = MagicMock(return_value=True)

    assert await player.stop() is True
    player.finish_current_track.assert_called_once_with("stop")
    mock_playback_backend.stop.assert_awaited_once()


def test_subsonic_completed_scrobble_sets_submission_true():
    source = object.__new__(SubsonicSource)
    source.api = MagicMock()
    source.api._api_request.return_value.json.return_value = {
        "subsonic-response": {"status": "ok"}
    }

    assert source.scrobble_completed("subsonic:tr-42", played_at=1700000000.0) is True

    args, _kwargs = source.api._api_request.call_args
    assert args[0] == "scrobble"
    assert args[1]["id"] == "tr-42"
    assert args[1]["submission"] == "true"
    assert args[1]["time"] == "1700000000000"
