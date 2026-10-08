"""SpeakerBrokerService.broadcast_clients_count_to_clients — the live
client-count feed for the now-playing card. Register / assign (attach +
detach) / unregister / re-home all funnel through the count broadcast."""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from app.core import Event, EventType, EventBus
from app.services.control_clients_service import ControlClient, ControlClientsService
from app.services.speaker_broker_service import SpeakerBrokerService
from app.services.speakers_service import Speaker, SpeakersService


def make_client(client_id, speaker_name=None, send_callback=None):
    return ControlClient(
        client_id=client_id, client_type="web", user_name="web_client",
        capabilities=[], connected_at=datetime.now(),
        websocket=MagicMock(), send_callback=send_callback,
        speaker_name=speaker_name,
    )


def make_speaker(name, mediaplayer_status="stop"):
    mediaplayer = MagicMock()
    mediaplayer.get_context = MagicMock(return_value={"status": mediaplayer_status})
    return Speaker(speaker_id="sp-x", name=name, backend="mpv", mediaplayer=mediaplayer)


def make_broker(clients, speakers):
    control_clients = ControlClientsService()
    control_clients._clients = clients
    speakers_service = SpeakersService()
    speakers_service._speakers = speakers
    return SpeakerBrokerService(control_clients, speakers_service, EventBus())


async def test_count_broadcast_payload_and_ghost_purge():
    send_callback = AsyncMock()
    ghost_id = "69f03134-6e17-4629-a880-c835b7f54c60"
    live = make_client("live-id", "bedroom", send_callback)
    speaker = make_speaker("bedroom")
    speaker.clients.update({"live-id", ghost_id})
    broker = make_broker({"live-id": live}, {"bedroom": speaker})

    await broker.broadcast_clients_count_to_clients(speaker)

    # the ghost is purged; the count reflects LIVE members only
    assert ghost_id not in speaker.clients
    (sent,) = send_callback.await_args_list
    assert sent.args[0]["type"] == "speaker_clients_changed"
    assert sent.args[0]["payload"] == {"speaker_name": "bedroom", "clients_count": 1}


async def test_unregister_tells_the_leftover_group():
    send_a = AsyncMock()
    send_b = AsyncMock()
    leaving = make_client("client-a", "kitchen", send_a)
    staying = make_client("client-b", "kitchen", send_b)
    speaker = make_speaker("kitchen")
    speaker.clients.update({"client-a", "client-b"})
    broker = make_broker(
        {"client-a": leaving, "client-b": staying}, {"kitchen": speaker})

    event = Event(EventType.UNREGISTER_CONTROL_CLIENT, {"client_id": "client-a", "websocket": leaving.websocket})
    await broker.handle_unregister_control_client(event)

    assert "client-a" not in speaker.clients
    # the count message goes to the STAYING client, reporting 1
    sent = send_b.await_args_list[-1].args[0]
    assert sent["type"] == "speaker_clients_changed"
    assert sent["payload"]["clients_count"] == 1


async def test_assign_moves_client_and_notifies_both_groups():
    send_moving, send_old = AsyncMock(), AsyncMock()
    moving = make_client("mv", "kitchen", send_moving)
    old_1 = make_client("old-guest", "kitchen", send_old)
    kitchen = make_speaker("kitchen")
    bedroom = make_speaker("bedroom")
    kitchen.clients.update({"mv", "old-guest"})
    broker = make_broker({"mv": moving, "old-guest": old_1},
                         {"kitchen": kitchen, "bedroom": bedroom})

    event = Event(EventType.ASSIGN_SPEAKER, {"client_id": "mv", "speaker_name": "bedroom"})
    await broker.handle_assign_speaker(event)

    assert "mv" in bedroom.clients
    assert "mv" not in kitchen.clients
    # the mover hears the new group (2 = current_track then count here: 1 member)
    moving_types = [c.args[0]["type"] for c in send_moving.await_args_list]
    assert "speaker_clients_changed" in moving_types
    mover_last = send_moving.await_args_list[-1].args[0]
    assert mover_last["payload"] == {"speaker_name": "bedroom", "clients_count": 1}
    # the kitchen group hears their count dropped
    kitchen_sent = send_old.await_args_list[-1].args[0]
    assert kitchen_sent["payload"] == {"speaker_name": "kitchen", "clients_count": 1}