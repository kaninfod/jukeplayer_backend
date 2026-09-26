"""Tests for PlaybackService.load_rfid: RFID_READ events carry the album_id
read from the card (cards are self-describing); the player is resolved via the
broker. There is no backend rfid→album database."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core import Event, EventType
from app.services.playback_service import PlaybackService


def make_service(speaker=None, event_bus=None):
    svc = PlaybackService(subsonic_service=MagicMock(), event_bus=event_bus or MagicMock())
    svc.load_from_album_id = AsyncMock(return_value=True)
    return svc, speaker


def default_speaker(device_name="living_room"):
    return MagicMock(mediaplayer=MagicMock(device_name=device_name))


def patched_container(monkeypatch, broker):
    monkeypatch.setattr("app.core.service_container.get_service", lambda name: broker)


@pytest.mark.asyncio
async def test_load_rfid_loads_card_album_on_default_speaker(monkeypatch):
    speaker = default_speaker("living_room")
    broker = MagicMock()
    broker.resolve_speaker.return_value = speaker
    patched_container(monkeypatch, broker)

    svc, _ = make_service()
    ok = await svc.load_rfid(Event(EventType.RFID_READ, {"rfid": "ABC", "album_id": "al-42"}))

    assert ok["ok"] is True
    broker.resolve_speaker.assert_called_once_with(client_id=None)
    args, kwargs = svc.load_from_album_id.await_args
    assert args[0] == "al-42"
    assert kwargs.get("player") is speaker.mediaplayer


@pytest.mark.asyncio
async def test_load_rfid_prefers_clients_speaker(monkeypatch):
    client_speaker = default_speaker("kitchen")
    broker = MagicMock()
    broker.resolve_speaker.return_value = client_speaker
    patched_container(monkeypatch, broker)

    svc, _ = make_service()
    ok = await svc.load_rfid(Event(EventType.RFID_READ, {"rfid": "ABC", "album_id": "al-7", "client_id": "c1"}))

    assert ok["ok"] is True
    broker.resolve_speaker.assert_called_once_with(client_id="c1")
    args, kwargs = svc.load_from_album_id.await_args
    assert kwargs.get("player") is client_speaker.mediaplayer


@pytest.mark.asyncio
async def test_load_rfid_card_without_album_id_is_ignored(monkeypatch):
    broker = MagicMock()
    patched_container(monkeypatch, broker)

    svc, _ = make_service()
    ok = await svc.load_rfid(Event(EventType.RFID_READ, {"rfid": "XYZ"}))

    assert ok["ok"] is False
    broker.resolve_speaker.assert_not_called()
    svc.load_from_album_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_load_rfid_no_speaker_fails_cleanly(monkeypatch):
    broker = MagicMock()
    broker.resolve_speaker.return_value = None
    patched_container(monkeypatch, broker)

    svc, _ = make_service()
    ok = await svc.load_rfid(Event(EventType.RFID_READ, {"rfid": "ABC", "album_id": "al-1"}))

    assert ok["ok"] is False
    svc.load_from_album_id.assert_not_awaited()