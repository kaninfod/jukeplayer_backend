from unittest.mock import AsyncMock, MagicMock, patch

from app.core import event_bus as bus
from app.websocket.mediaplayer_ws import WebSocketConnection


def make_connection(client_id="web-1"):
    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    conn = WebSocketConnection(websocket, "127.0.0.1", 50000, "test-agent", client_id)
    return conn, websocket


async def test_play_random_sends_pick_and_reason():
    conn, websocket = make_connection()
    result = [{
        "ok": True,
        "speaker": "living_room",
        "album_id": "al-1",
        "artist": "Artist",
        "album": "Album",
        "reason": "never played; artist you play often",
        "mode": "smart",
    }]

    with patch.object(bus, "aemit", AsyncMock(return_value=result)) as emit:
        await conn.handle_play_random({"device_name": "living_room"})

    websocket.send_json.assert_any_await({
        "type": "random_pick",
        "payload": {
            "speaker": "living_room",
            "album_id": "al-1",
            "artist": "Artist",
            "album": "Album",
            "reason": "never played; artist you play often",
            "mode": "smart",
        },
    })
    event = emit.await_args.args[0]
    assert event.payload["device_name"] == "living_room"


async def test_play_random_sends_notification_on_error():
    conn, websocket = make_connection()
    result = [{"ok": False, "error": "No speaker could be resolved"}]

    with patch.object(bus, "aemit", AsyncMock(return_value=result)):
        await conn.handle_play_random({})

    websocket.send_json.assert_any_await({
        "type": "notification",
        "payload": {"status": "error", "message": "No speaker could be resolved"},
    })
