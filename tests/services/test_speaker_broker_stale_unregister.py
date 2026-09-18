"""Regression tests for the re-registration race (stale unregister) and
ghost-client handling in SpeakerBrokerService.

Scenario: a web client reuses its client_id across WS reconnects. The old
connection's cleanup can fire after the new registration and must not delete
the live registration (root cause of the ASSIGN_SPEAKER KeyError seen in
jukebox.log on 2026-09-18)."""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from app.core import Event, EventType, EventBus
from app.services.control_clients_service import ControlClient, ControlClientsService
from app.services.speaker_broker_service import SpeakerBrokerService
from app.services.speakers_service import Speaker, SpeakersService


def make_client(client_id, websocket=None, send_callback=None):
    return ControlClient(
        client_id=client_id,
        client_type="web",
        user_name="web_client",
        capabilities=[],
        connected_at=datetime.now(),
        websocket=websocket,
        send_callback=send_callback,
    )


def make_speaker(name):
    mediaplayer = MagicMock()
    mediaplayer.get_context = MagicMock(return_value={"status": "stop"})
    return Speaker(speaker_id="sp-1", name=name, backend="mpv", mediaplayer=mediaplayer)


def make_broker(clients, speakers):
    control_clients = ControlClientsService()
    control_clients._clients = clients
    speakers_service = SpeakersService()
    speakers_service._speakers = speakers
    return SpeakerBrokerService(control_clients, speakers_service, EventBus())


async def test_stale_unregister_does_not_delete_reregistered_client():
    old_ws, new_ws = MagicMock(), MagicMock()
    client_id = "69f03134-6e17-4629-a880-c835b7f54c60"
    client = make_client(client_id, websocket=new_ws)
    speaker = make_speaker("kitchen")
    speaker.clients.add(client_id)
    broker = make_broker({client_id: client}, {"kitchen": speaker})

    # Late cleanup from the OLD connection, arriving after re-registration
    event = Event(EventType.UNREGISTER_CONTROL_CLIENT, {"client_id": client_id, "websocket": old_ws})
    await broker.handle_unregister_control_client(event)

    assert client_id in broker.control_clients._clients
    assert client_id in speaker.clients


async def test_live_unregister_still_removes_client():
    ws = MagicMock()
    client_id = "client-a"
    client = make_client(client_id, websocket=ws)
    speaker = make_speaker("kitchen")
    speaker.clients.add(client_id)
    broker = make_broker({client_id: client}, {"kitchen": speaker})

    event = Event(EventType.UNREGISTER_CONTROL_CLIENT, {"client_id": client_id, "websocket": ws})
    await broker.handle_unregister_control_client(event)

    assert client_id not in broker.control_clients._clients
    assert client_id not in speaker.clients


async def test_unregister_without_websocket_keeps_old_behavior():
    client_id = "client-a"
    client = make_client(client_id, websocket=MagicMock())
    broker = make_broker({client_id: client}, {})

    # Emitters that do not carry a websocket must behave as before
    event = Event(EventType.UNREGISTER_CONTROL_CLIENT, {"client_id": client_id})
    await broker.handle_unregister_control_client(event)

    assert client_id not in broker.control_clients._clients


async def test_assign_speaker_for_unknown_client_leaves_no_ghost():
    speaker = make_speaker("living_room")
    broker = make_broker({}, {"living_room": speaker})

    event = Event(EventType.ASSIGN_SPEAKER, {"client_id": "ghost-id", "speaker_name": "living_room"})
    await broker.handle_assign_speaker(event)

    assert "ghost-id" not in speaker.clients


async def test_assign_speaker_sets_speaker_name_and_broadcasts():
    ws = MagicMock()
    send_callback = AsyncMock()
    client_id = "client-a"
    client = make_client(client_id, websocket=ws, send_callback=send_callback)
    client.speaker_name = "kitchen"
    speaker = make_speaker("kitchen")
    broker = make_broker({client_id: client}, {"kitchen": speaker})

    event = Event(EventType.ASSIGN_SPEAKER, {"client_id": client_id, "speaker_name": "kitchen"})
    await broker.handle_assign_speaker(event)

    assert client.speaker_name == "kitchen"
    assert client_id in speaker.clients
    send_callback.assert_awaited_once()


async def test_broadcast_purges_ghost_clients():
    send_callback = AsyncMock()
    live_id, ghost_id = "live-id", "69f03134-6e17-4629-a880-c835b7f54c60"
    client = make_client(live_id, websocket=MagicMock(), send_callback=send_callback)
    client.speaker_name = "bedroom"
    speaker = make_speaker("bedroom")
    speaker.clients.update({live_id, ghost_id})
    broker = make_broker({live_id: client}, {"bedroom": speaker})

    await broker.broadcast_context_to_clients(speaker)

    assert ghost_id not in speaker.clients
    assert live_id in speaker.clients
    send_callback.assert_awaited_once()