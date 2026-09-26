"""Regression tests for the speaker-routing fallback in SpeakerBrokerService.

Scenario: bare HTTP control endpoints (Pi client buttons, HA) emit events
without client_id/device_name. These used to crash the broker with an
UnboundLocalError on `speaker`. They must now route to the device named in
the payload (backend events) or the default speaker (control commands)."""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from app.core import Event, EventType, EventBus
from app.services.control_clients_service import ControlClient, ControlClientsService
from app.services.speaker_broker_service import SpeakerBrokerService
from app.services.speakers_service import Speaker, SpeakersService


def make_speaker(name, status="stop"):
    mediaplayer = MagicMock()
    mediaplayer.get_context = MagicMock(return_value={"status": status})
    for action in ("play_pause", "next_track", "previous_track", "stop",
                   "handle_volume_up", "handle_volume_down", "toggle_repeat"):
        setattr(mediaplayer, action, AsyncMock(return_value=True))
    return Speaker(speaker_id=f"sp-{name}", name=name, backend="mpv", mediaplayer=mediaplayer)


def make_broker(speakers):
    speakers_service = SpeakersService()
    speakers_service._speakers = speakers
    return SpeakerBrokerService(MagicMock(), speakers_service, EventBus())


@pytest.mark.asyncio
async def test_event_without_client_id_falls_back_to_default_speaker():
    speaker = make_speaker("living_room")
    broker = make_broker({"living_room": speaker})

    await broker._execute_media_action(Event(EventType.PLAY_PAUSE, {}), "play_pause")

    speaker.mediaplayer.play_pause.assert_awaited_once()


@pytest.mark.asyncio
async def test_event_with_device_name_routes_to_that_speaker():
    kitchen = make_speaker("kitchen")
    living_room = make_speaker("living_room")
    broker = make_broker({"kitchen": kitchen, "living_room": living_room})

    event = Event(EventType.TRACK_FINISHED, {"device_name": "kitchen"})
    await broker._execute_media_action(event, "next_track")

    kitchen.mediaplayer.next_track.assert_awaited_once()
    living_room.mediaplayer.next_track.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_client_id_falls_back_to_default_speaker():
    living_room = make_speaker("living_room")
    broker = make_broker({"living_room": living_room})

    # client_id provided but not registered (stale client) -> must not no-op
    await broker._execute_media_action(
        Event(EventType.PLAY_PAUSE, {"client_id": "gone-client"}), "play_pause")

    living_room.mediaplayer.play_pause.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_speakers_configured_is_a_clean_noop():
    broker = make_broker({})

    # Must not raise (previously UnboundLocalError)
    await broker._execute_media_action(Event(EventType.STOP, {}), "stop")


def test_resolve_speaker_priority_client_then_device_then_default():
    kitchen = make_speaker("kitchen")
    living_room = make_speaker("living_room")

    control_clients = ControlClientsService()
    control_clients._clients["c1"] = ControlClient(
        client_id="c1", client_type="web", user_name="tester",
        capabilities=[], connected_at=datetime.now(), speaker_name="kitchen")
    speakers_service = SpeakersService()
    speakers_service._speakers = {"kitchen": kitchen, "living_room": living_room}
    broker = SpeakerBrokerService(control_clients, speakers_service, EventBus())

    # 1. Client wins
    assert broker.resolve_speaker(client_id="c1") is kitchen
    # 2. device_name wins when no client context
    assert broker.resolve_speaker(device_name="kitchen") is kitchen
    # 3. Default speaker when nothing else matches (flagged default)
    speakers_service._default_name = "living_room"
    assert broker.resolve_speaker() is living_room
    # 3b. Without a flag, the first configured speaker is the fallback default
    speakers_service._default_name = None
    assert broker.resolve_speaker() is kitchen
    # 4. Unknown client falls back to the flagged default
    speakers_service._default_name = "living_room"
    assert broker.resolve_speaker(client_id="ghost") is living_room
    # 5. Nothing configured -> None
    empty_broker = SpeakerBrokerService(control_clients, SpeakersService(), EventBus())
    assert empty_broker.resolve_speaker() is None


@pytest.mark.asyncio
async def test_track_changed_broadcasts_context_to_speaker_clients():
    speaker = make_speaker("kitchen")
    broker = make_broker({"kitchen": speaker})
    broker.broadcast_context_to_clients = AsyncMock()

    await broker.handle_track_changed(Event(EventType.TRACK_CHANGED, {"device_name": "kitchen"}))

    broker.broadcast_context_to_clients.assert_awaited_once_with(speaker)


@pytest.mark.asyncio
async def test_broadcast_volume_sends_dict_payload_with_muted():
    speaker = make_speaker("kitchen")
    speaker.mediaplayer.volume_manager.volume = 42
    speaker.mediaplayer.volume_manager.is_muted = True

    client = ControlClient(
        client_id="c1", client_type="web", user_name="tester",
        capabilities=[], connected_at=datetime.now(),
        send_callback=AsyncMock())
    control_clients = ControlClientsService()
    control_clients._clients["c1"] = client
    speakers_service = SpeakersService()
    speakers_service._speakers = {"kitchen": speaker}
    broker = SpeakerBrokerService(control_clients, speakers_service, EventBus())
    speaker.clients.add("c1")

    await broker.broadcast_volume_to_clients(speaker)

    client.send_callback.assert_awaited_once()
    message = client.send_callback.await_args.args[0]
    assert message["type"] == "volume_changed"
    assert message["payload"]["volume"] == 42
    assert message["payload"]["muted"] is True


@pytest.mark.asyncio
async def test_volume_changed_event_updates_state_and_broadcasts():
    """Device-side volume changes (cast status callback) update local state
    and are pushed to clients — never written back to the device."""
    from unittest.mock import MagicMock as _MagicMock
    speaker = make_speaker("kitchen")
    speaker.mediaplayer.volume_manager = _MagicMock()
    speaker.mediaplayer.volume_manager.set_local_volume = _MagicMock()
    speaker.mediaplayer.volume_manager.volume = 33
    speaker.mediaplayer.volume_manager.is_muted = False

    client = ControlClient(
        client_id="c1", client_type="web", user_name="tester",
        capabilities=[], connected_at=datetime.now(),
        send_callback=AsyncMock())
    control_clients = ControlClientsService()
    control_clients._clients["c1"] = client
    speakers_service = SpeakersService()
    speakers_service._speakers = {"kitchen": speaker}
    broker = SpeakerBrokerService(control_clients, speakers_service, EventBus())
    speaker.clients.add("c1")

    await broker.handle_volume_changed(Event(EventType.VOLUME_CHANGED, {
        "device_name": "kitchen", "volume": 33, "muted": False}))

    speaker.mediaplayer.volume_manager.set_local_volume.assert_called_once_with(33, False)
    client.send_callback.assert_awaited_once()
    message = client.send_callback.await_args.args[0]
    assert message["payload"]["volume"] == 33