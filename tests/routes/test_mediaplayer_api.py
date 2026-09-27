"""Tests for the modernized /api/mediaplayer + /api/output routes.

Contract under test:
- every transport action returns the uniform ActionResult envelope
- routing context: client_id → speaker (name) → default, resolved by the
  broker
- /api/output: status/devices/options are gone; /speakers carries
  default_speaker; /switch assigns a client or sets the system default
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app, startup_event


@pytest.fixture
async def initialized_app(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.config.CONFIG_FILE", str(tmp_path / "config.json"))
    # the app.core event_bus is a module-level singleton: drop the handlers
    # accumulated by previous tests' startup_event calls, or stale brokers
    # from older containers answer first (result[0] routing pollution)
    from app.core import event_bus as module_bus
    module_bus._handlers.clear()
    await startup_event()


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _stub_context(status="IDLE", volume=50, muted=False, repeat_album=False):
    return {"status": status, "volume": volume, "muted": muted,
            "repeat_album": repeat_album, "current_track": None, "current_index": 0}


def _inject_speaker(name, context=None, default=False):
    """Inject a registry speaker whose mediaplayer is fully mocked (no
    backend I/O) — the routing + envelope contract needs no real player."""
    from app.core.service_container import get_service
    from app.services.speakers_service import Speaker

    ss = get_service("speakers_service")
    mp = MagicMock()
    mp.play_pause = AsyncMock()
    mp.stop = AsyncMock()
    mp.previous_track = AsyncMock()
    mp.next_track = AsyncMock(return_value=True)
    mp.handle_volume_up = AsyncMock()
    mp.handle_volume_down = AsyncMock()
    mp.handle_volume_mute = AsyncMock()
    mp.toggle_repeat = AsyncMock()
    mp.set_volume = AsyncMock()
    mp.play_track = AsyncMock()
    mp.get_context = MagicMock(return_value=context or _stub_context())
    speaker = Speaker(name=name, speaker_id=name, mediaplayer=mp,
                      backend="chromecast", speaker_type="chromecast")
    ss._speakers[name] = speaker
    if default:
        ss._default_name = name
    return speaker


def _inject_control_client(client_id, speaker_name=None):
    from app.core.service_container import get_service
    from app.services.control_clients_service import ControlClient

    ccs = get_service("control_clients_service")
    client = ControlClient(client_id=client_id, client_type="home_assistant",
                           user_name="Test HA", capabilities=[],
                           connected_at=datetime.now(), speaker_name=speaker_name)
    client.send_callback = AsyncMock()
    ccs._clients[client_id] = client
    return client


def _get_service(name):
    from app.core.service_container import get_service
    return get_service(name)


@pytest.mark.asyncio
async def test_transport_envelope_is_uniform(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _inject_speaker("living_room", default=True)

        resp = await client.post("/api/mediaplayer/play_pause")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["speaker"] == "living_room"
        # envelope shape: only the documented keys
        assert set(body.keys()) == {"status", "message", "speaker", "volume", "muted", "repeat_album"}


@pytest.mark.asyncio
async def test_transport_speaker_param_targets_the_named_speaker(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _inject_speaker("living_room", default=True)
        _inject_speaker("kitchen", context=_stub_context(status="PLAY", volume=88))

        resp = await client.post("/api/mediaplayer/volume_set?volume=88&speaker=kitchen")
        body = resp.json()
        assert body["status"] == "success"
        assert body["speaker"] == "kitchen"   # targeted, not the default
        assert body["volume"] == 88

        # without a context the default speaker is used
        resp = await client.post("/api/mediaplayer/play_pause")
        assert resp.json()["speaker"] == "living_room"


@pytest.mark.asyncio
async def test_transport_client_id_resolves_via_broker(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _inject_speaker("living_room", default=True)
        _inject_control_client("ha-1", speaker_name="kitchen")
        _inject_speaker("kitchen", context=_stub_context(volume=12))

        resp = await client.post("/api/mediaplayer/volume_up?client_id=ha-1")
        body = resp.json()
        assert body["status"] == "success"
        assert body["speaker"] == "kitchen"   # via the client's speaker, not the default


@pytest.mark.asyncio
async def test_next_track_reports_end_of_playlist(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        speaker = _inject_speaker("living_room", default=True)
        speaker.mediaplayer.next_track = AsyncMock(return_value=False)

        resp = await client.post("/api/mediaplayer/next_track")
        body = resp.json()
        assert body["status"] == "success"
        assert "End of playlist" in body["message"]


@pytest.mark.asyncio
async def test_transport_error_when_nothing_resolves(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/mediaplayer/stop")
        body = resp.json()
        assert body["status"] == "error"
        assert "No speaker could be resolved" in body["message"]


@pytest.mark.asyncio
async def test_status_targets_resolved_speaker(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _inject_speaker("living_room", default=True)
        _inject_speaker("kitchen", context=_stub_context(volume=12))

        resp = await client.get("/api/mediaplayer/status?speaker=kitchen")
        body = resp.json()
        assert body["volume"] == 12   # kitchen's context, not the default's

        # default fallback when no context is given
        resp = await client.get("/api/mediaplayer/status")
        assert resp.json()["volume"] == 50


@pytest.mark.asyncio
async def test_output_speakers_carries_default_speaker(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _inject_speaker("living_room", default=True)

        resp = await client.get("/api/output/speakers")
        body = resp.json()
        assert body["status"] == "ok"
        assert body["default_speaker"] == "living_room"
        assert "living_room" in body["devices"]


@pytest.mark.asyncio
async def test_output_single_player_endpoints_are_gone(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path in ("/api/output/status", "/api/output/options", "/api/output/devices"):
            assert (await client.get(path)).status_code == 404, path


@pytest.mark.asyncio
async def test_output_switch_assigns_registered_client(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _inject_speaker("living_room", default=True)
        _inject_speaker("kitchen")
        client_obj = _inject_control_client("ha-1")

        resp = await client.post("/api/output/switch",
                                 json={"speaker": "kitchen", "client_id": "ha-1"})
        body = resp.json()
        assert body["status"] == "success"
        assert body["speaker"] == "kitchen"
        # the assignment landed on the live client
        assert client_obj.speaker_name == "kitchen"


@pytest.mark.asyncio
async def test_output_switch_without_client_sets_default(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # store-backed speakers: set_default writes the config store
        await client.post("/kiosk/system/connect/manual",
                          data={"name": "living_room", "backend": "chromecast"})
        await client.post("/kiosk/system/connect/manual",
                          data={"name": "kitchen", "backend": "chromecast"})

        resp = await client.post("/api/output/switch", json={"speaker": "kitchen"})
        body = resp.json()
        assert body["status"] == "success"
        assert body["speaker"] == "kitchen"

        resp = await client.get("/api/output/speakers")
        assert resp.json()["default_speaker"] == "kitchen"


@pytest.mark.asyncio
async def test_output_switch_unknown_speaker_is_an_error(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _inject_speaker("living_room", default=True)

        resp = await client.post("/api/output/switch", json={"speaker": "ghost"})
        assert resp.json()["status"] == "error"


def test_websocket_route_handler_is_importable():
    """Regression: the routes rewrite dropped the websocket_status_handler
    import — the app started fine, every HTTP route worked, but the FIRST
    WebSocket connection raised NameError and every client was rejected
    (500 on /ws/mediaplayer/events). The name must resolve at call time."""
    from app.routes import mediaplayer as mp_routes
    from app.websocket.mediaplayer_ws import websocket_status_handler

    assert mp_routes.websocket_status_handler is websocket_status_handler


def test_websocket_handshake_registers_client(monkeypatch, tmp_path):
    """A real WebSocket handshake must be accepted and answer the
    register_client protocol — the path every client (web, ESP32, HA) uses."""
    import asyncio

    from fastapi.testclient import TestClient

    monkeypatch.setattr("app.config.config.CONFIG_FILE", str(tmp_path / "config.json"))
    from app.core import event_bus as module_bus
    module_bus._handlers.clear()
    asyncio.run(startup_event())

    with TestClient(app) as ws_client:
        with ws_client.websocket_connect("/ws/mediaplayer/events?detail=full") as ws:
            ws.send_json({
                "type": "register_client",
                "payload": {
                    "client_type": "home_assistant",
                    "client_name": "Test HA",
                    "capabilities": ["websocket_status"],
                    "device_id": "living_room",
                },
            })
            response = ws.receive_json()
            assert response["type"] == "register_response"
            assert response["payload"]["status"] == "success"
            assert response["payload"]["client_id"]

@pytest.mark.asyncio
async def test_device_card_shows_handover_pill(initialized_app):
    """A flagged BT speaker renders the handover pill (auto-reconnect paused)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _inject_speaker("living_room", default=True)
        from app.services.speakers_service import Speaker
        from unittest.mock import MagicMock
        ss = _get_service("speakers_service")
        boom = Speaker(name="boom_3", speaker_id="boom_3", mediaplayer=MagicMock(),
                       backend="mpv", speaker_type="bluetooth")
        boom.bt_mac = "10:94:97:0F:CB:BF"
        boom.user_disconnected = True
        ss._speakers["boom_3"] = boom

        page = await client.get("/kiosk/devices")
        assert page.status_code == 200
        # the BT state pill goes yellow in handover (no separate pill)
        assert "text-bg-warning" in page.text
        assert "auto-reconnect paused" in page.text
        assert "Handover" not in page.text.replace(
            "Handover: auto-reconnect paused", "")

        # unflagged speakers keep the plain grey disconnected pill
        boom.user_disconnected = False
        page = await client.get("/kiosk/devices")
        assert "text-bg-warning" not in page.text
