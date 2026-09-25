"""Tests for the Bluetooth API + config card (Phase C)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app, startup_event


@pytest.fixture
def anyio_backend():
    return "asyncio"


class StubBT:
    """BluetoothService double — no subprocess calls."""

    def __init__(self):
        self._connected = True

    def status(self):
        return {"powered": True, "controller": "AA:BB:CC:DD:EE:FF"}

    def devices(self):
        return [self._device()]

    def info(self, mac):
        return {"paired": True, "trusted": True, "connected": self._connected,
                "name": "BOOM 3", "a2dp_sink": True, "uuids": [],
                "class": 0x240414, "icon": "audio-card", "audio": True}

    def scan(self, seconds=None):
        return [self._device(), self._junk_device()]

    def bluez_sinks(self):
        sinks = [{"index": "1", "name": "bluez_sink.10_94_97_0F_CB_BF.a2dp_sink",
                  "state": "SUSPENDED"}] if self._connected else []
        return sinks

    def sink_for_device(self, mac):
        if mac != "10:94:97:0F:CB:BF" or not self._connected:
            return None
        return "pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink"

    def pair_and_connect(self, mac):
        self._connected = True
        return {"mac": mac, "paired": True, "trusted": True, "connected": True,
                "name": "BOOM 3", "error": None}

    def connect(self, mac):
        self._connected = True
        return {"mac": mac, "connected": True, "paired": True, "error": None}

    def disconnect(self, mac):
        self._connected = False
        return {"mac": mac, "connected": False}

    def forget(self, mac):
        return {"mac": mac, "removed": True}

    def battery_percent(self, mac, uuids=None):
        return 42 if mac == "10:94:97:0F:CB:BF" else None

    def auto_connect_trusted(self):
        pass

    @staticmethod
    def _device():
        return {"mac": "10:94:97:0F:CB:BF", "name": "BOOM 3", "paired": True,
                "trusted": True, "connected": True, "a2dp_sink": True,
                "uuids": [], "audio": True}

    @staticmethod
    def _junk_device():
        """Unpaired, unnamed (name == MAC), non-audio — must be hidden."""
        mac = "11:22:33:44:55:66"
        return {"mac": mac, "name": mac, "paired": False, "trusted": False,
                "connected": False, "a2dp_sink": False, "uuids": [],
                "audio": False}


@pytest.fixture
def stub_bluetooth(monkeypatch):
    """Swap the container's bluetooth_service factory before startup."""
    import app.core.service_container as sc
    monkeypatch.setattr(sc, "create_bluetooth_service", lambda c: StubBT())


class FakeMediaPlayer:
    def __init__(self, event_bus=None, playback_backend=None, device_name=None):
        self.device_name = device_name
        self.playback_backend = playback_backend
        self.volume_manager = SimpleNamespace(
            sync_volume_from_backend=AsyncMock(return_value=50))

    def get_context(self, minimal=False):
        return {"status": "idle"}

    async def stop(self):
        pass


@pytest.fixture
def stub_live_construction(monkeypatch):
    import app.services as services_pkg
    import app.playback_backends.factory as factory
    from types import SimpleNamespace as NS

    def fake_backend(backend_name, device_name=None, options=None):
        return NS(device_name=device_name, is_connected=lambda: True,
                  ensure_connected=None, disconnect=MagicMock())

    monkeypatch.setattr(factory, "get_playback_backend_by_name", fake_backend)
    monkeypatch.setattr(services_pkg, "MediaPlayerService", FakeMediaPlayer)


@pytest.fixture
async def initialized_app(monkeypatch, tmp_path, stub_bluetooth, stub_live_construction):
    monkeypatch.setattr("app.config.config.CONFIG_FILE", str(tmp_path / "config.json"))
    await startup_event()


@pytest.mark.asyncio
async def test_bluetooth_status_api(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/bluetooth/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["powered"] is True
        assert body["devices"][0]["name"] == "BOOM 3"
        assert body["devices"][0]["connected"] is True


@pytest.mark.asyncio
async def test_bluetooth_scan_api(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/bluetooth/scan?seconds=5")
        assert resp.status_code == 200
        assert resp.json()["devices"][0]["mac"] == "10:94:97:0F:CB:BF"


@pytest.mark.asyncio
async def test_bluetooth_pair_validates_mac(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bad = await client.post("/api/bluetooth/pair", json={"mac": "not-a-mac"})
        assert bad.status_code == 400

        good = await client.post("/api/bluetooth/pair", json={"mac": "10:94:97:0F:CB:BF"})
        assert good.status_code == 200
        assert good.json()["connected"] is True


@pytest.mark.asyncio
async def test_bluetooth_sinks_api(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/bluetooth/sinks")
        assert resp.status_code == 200
        assert resp.json()["sinks"][0]["name"] == "bluez_sink.10_94_97_0F_CB_BF.a2dp_sink"


@pytest.mark.asyncio
async def test_connect_card_renders_and_pair_adds_speaker(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        card = await client.get("/kiosk/system/connect")
        assert card.status_code == 200
        assert 'id="connect-speaker-card"' in card.text

        scan = await client.get("/kiosk/system/connect/scan/bt")
        assert scan.status_code == 200
        assert "BOOM 3" in scan.text

        pair = await client.post("/kiosk/system/connect/pair", data={"mac": "10:94:97:0F:CB:BF"})
        assert pair.status_code == 200
        assert "Paired and connected" in pair.text
        assert "added as speaker" in pair.text

        listing = await client.get("/api/config/speakers")
        added = next(s for s in listing.json()["speakers"] if s["name"] == "boom_3")
        assert added["backend"] == "mpv"
        assert added["options"]["audio_device"] == "pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink"


@pytest.mark.asyncio
async def test_connect_card_managed_note(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/kiosk/system/connect/pair", data={"mac": "10:94:97:0F:CB:BF"})
        scan = await client.get("/kiosk/system/connect/scan/bt")
        text = " ".join(scan.text.split())
        assert "Already added as speaker (managed in the Speakers card): BOOM 3" in text
        assert "10:94:97:0F:CB:BF" not in text   # hidden from the pair list


@pytest.mark.asyncio
async def test_connect_card_add_cc(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/kiosk/system/connect/add-cc", data={"name": "Living Room"})
        assert resp.status_code == 200
        listing = await client.get("/api/config/speakers")
        added = next(s for s in listing.json()["speakers"] if s["name"] == "living_room")
        assert added["backend"] == "chromecast"


@pytest.mark.asyncio
async def test_connect_card_manual(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/kiosk/system/connect/manual",
                                 data={"name": "dac_test", "backend": "mpv", "audio_device": ""})
        assert resp.status_code == 200
        listing = await client.get("/api/config/speakers")
        added = next(s for s in listing.json()["speakers"] if s["name"] == "dac_test")
        assert added["backend"] == "mpv"


@pytest.mark.asyncio
async def test_speakers_card_shows_type_and_state(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/kiosk/system/connect/pair", data={"mac": "10:94:97:0F:CB:BF"})
        page = await client.get("/kiosk/config")
        html = " ".join(page.text.split())
        assert "Bluetooth" in html
        assert "BOOM 3" in html
        # the BT connect/disconnect buttons moved to the device page
        assert "bt-connect" not in html and "bt-disconnect" not in html


@pytest.mark.asyncio
async def test_device_card_bt_controls(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/kiosk/system/connect/pair", data={"mac": "10:94:97:0F:CB:BF"})

        page = await client.get("/kiosk/devices")
        assert page.status_code == 200
        html = " ".join(page.text.split())
        assert "BT connected" in html
        assert "42%" in html
        assert "10:94:97:0F:CB:BF" in html

        resp = await client.post("/kiosk/devices/bt-toggle", json={"name": "boom_3"})
        assert resp.json()["connected"] is False
        page = await client.get("/kiosk/devices")
        assert "BT disconnected" in " ".join(page.text.split())

        resp = await client.post("/kiosk/devices/bt-toggle", json={"name": "boom_3"})
        assert resp.json()["connected"] is True


@pytest.mark.asyncio
async def test_device_card_bt_toggle_without_bt_device(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/config/speakers", json={"name": "living_room"})
        resp = await client.post("/kiosk/devices/bt-toggle", json={"name": "living_room"})
        assert resp.status_code == 400
        assert "not a Bluetooth speaker" in resp.json()["detail"]