import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core import Event, EventType, EventBus
from app.recommendations.models import AlbumPick
from app.speakers.speaker_broker_service import SpeakerBrokerService
from app.speakers.speakers_service import Speaker, SpeakersService


def _speaker():
    mediaplayer = MagicMock()
    mediaplayer.get_context = MagicMock(return_value={"status": "idle"})
    return Speaker(
        speaker_id="sp-living",
        name="living_room",
        backend="mpv",
        mediaplayer=mediaplayer,
    )


@pytest.mark.asyncio
async def test_handle_play_random_picks_and_starts_playback(monkeypatch):
    speaker = _speaker()
    speakers = SpeakersService()
    speakers._speakers = {"living_room": speaker}
    broker = SpeakerBrokerService(MagicMock(), speakers, EventBus())
    broker.broadcast_context_to_clients = AsyncMock()

    pick = AlbumPick(
        album_id="al-42",
        artist="Greta Van Fleet",
        album="The Battle at Garden’s Gate",
        year="2021",
        reason="never played; artist you play often",
        score=0.91,
        components={"neglect": 1.0},
    )
    recommendation_service = MagicMock()
    recommendation_service.pick = AsyncMock(return_value=pick)
    playback_service = MagicMock()
    playback_service.load_from_album_id = AsyncMock(return_value=True)

    def fake_get_service(name):
        return {
            "recommendation_service": recommendation_service,
            "playback_service": playback_service,
        }[name]

    monkeypatch.setattr("app.core.service_container.get_service", fake_get_service)

    result = await broker.handle_play_random(
        Event(EventType.PLAY_RANDOM, {"device_name": "living_room"})
    )

    assert result["ok"] is True
    assert result["speaker"] == "living_room"
    assert result["album_id"] == "al-42"
    assert "never played" in result["reason"]
    recommendation_service.pick.assert_awaited_once_with(device_name="living_room")
    playback_service.load_from_album_id.assert_awaited_once_with(
        "al-42", player=speaker.mediaplayer
    )
    broker.broadcast_context_to_clients.assert_awaited_once_with(speaker)


@pytest.mark.asyncio
async def test_handle_play_random_without_speaker_is_a_clean_error():
    broker = SpeakerBrokerService(MagicMock(), SpeakersService(), EventBus())
    result = await broker.handle_play_random(Event(EventType.PLAY_RANDOM, {}))
    assert result["ok"] is False
    assert "No speaker" in result["error"]
