"""Unit tests for WebSocketConnection.handle_device_reset routing."""
from unittest.mock import AsyncMock, MagicMock, patch

from app.websocket.mediaplayer_ws import WebSocketConnection


def make_connection(sender_id="sender-client-id"):
    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    conn = WebSocketConnection(websocket, "127.0.0.1", 50000, "test-agent", sender_id)
    return conn, websocket


class FakeClientsService:
    def __init__(self, clients):
        self._clients = clients

    def get_client(self, client_id):
        return self._clients.get(client_id)


def make_target(send_callback=None):
    client = MagicMock()
    client.send_callback = send_callback if send_callback is not None else AsyncMock()
    return client


async def test_forwards_device_reset_to_target_client():
    conn, websocket = make_connection()
    send_callback = AsyncMock()
    service = FakeClientsService({"esp32-target": make_target(send_callback)})

    with patch("app.websocket.mediaplayer_ws.get_service", return_value=service):
        await conn.handle_device_reset({"client_id": "esp32-target"})

    send_callback.assert_awaited_once_with({"type": "device_reset", "payload": {}})
    websocket.send_json.assert_any_await({
        "type": "device_reset_response",
        "payload": {"status": "ok", "client_id": "esp32-target"},
    })


async def test_error_response_when_target_unknown():
    conn, websocket = make_connection()
    service = FakeClientsService({})

    with patch("app.websocket.mediaplayer_ws.get_service", return_value=service):
        await conn.handle_device_reset({"client_id": "gone-client"})

    websocket.send_json.assert_any_await({
        "type": "device_reset_response",
        "payload": {
            "status": "error",
            "message": "Client not found or not connected",
            "client_id": "gone-client",
        },
    })


async def test_error_response_when_client_id_missing():
    conn, websocket = make_connection()
    service = FakeClientsService({})

    with patch("app.websocket.mediaplayer_ws.get_service", return_value=service):
        await conn.handle_device_reset({})

    websocket.send_json.assert_any_await({
        "type": "device_reset_response",
        "payload": {
            "status": "error",
            "message": "Client not found or not connected",
            "client_id": None,
        },
    })