"""Tests for the configuration API (/api/config)."""
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app, startup_event


@pytest.fixture
async def initialized_app(monkeypatch, tmp_path):
    # CONFIG_FILE is a class attr resolved at import — patch it, not the env
    # (setenv here never reached the store and tests leaked into the real file)
    monkeypatch.setattr("app.config.config.CONFIG_FILE", str(tmp_path / "config.json"))
    await startup_event()   # builds the service container (empty store in tmp)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.asyncio
async def test_effective_config_masks_password(monkeypatch, tmp_path):
    # CONFIG_FILE is a class attr resolved at import — patch it, not the env
    # (setenv here never reached the store and tests leaked into the real file)
    monkeypatch.setattr("app.config.config.CONFIG_FILE", str(tmp_path / "config.json"))

    await startup_event()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/config")
        assert resp.status_code == 200
        body = resp.json()
        pw = body["sections"]["subsonic"]["keys"]["password"]
        assert pw["masked"] is True
        assert pw["value"] == ""


@pytest.mark.asyncio
async def test_update_subsonic_saves_and_masks(monkeypatch, tmp_path):
    # CONFIG_FILE is a class attr resolved at import — patch it, not the env
    # (setenv here never reached the store and tests leaked into the real file)
    monkeypatch.setattr("app.config.config.CONFIG_FILE", str(tmp_path / "config.json"))

    await startup_event()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put("/api/config/subsonic", json={
            "url": "http://gonic:80", "user": "u", "password": "secret"})
        assert resp.status_code == 200
        assert resp.json()["password_set"] is True

        # second update with blank password keeps the stored one
        resp2 = await client.put("/api/config/subsonic", json={"url": "http://gonic:80", "user": "u2"})
        assert resp2.status_code == 200
        assert resp2.json()["password_set"] is True

        # empty required field rejected
        resp3 = await client.put("/api/config/subsonic", json={"url": "", "user": "u"})
        assert resp3.status_code == 400


@pytest.mark.asyncio
async def test_logging_level_applies_live(monkeypatch, tmp_path):
    import logging
    # CONFIG_FILE is a class attr resolved at import — patch it, not the env
    # (setenv here never reached the store and tests leaked into the real file)
    monkeypatch.setattr("app.config.config.CONFIG_FILE", str(tmp_path / "config.json"))

    await startup_event()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put("/api/config/logging", json={"level": "WARNING"})
        assert resp.status_code == 200
        assert resp.json() == {"status": "saved", "applies": "live", "level": "WARNING"}
        assert logging.getLogger().level == logging.WARNING

        bad = await client.put("/api/config/logging", json={"level": "NOPE"})
        assert bad.status_code == 400

    logging.getLogger().setLevel(logging.INFO)


# --- Speakers (Phase B) --------------------------------------------------------

class FakeVolumeManager:
    def __init__(self):
        from unittest.mock import AsyncMock
        self.sync_volume_from_backend = AsyncMock(return_value=50)


class FakeMediaPlayer:
    """Stands in for MediaPlayerService so no real backend/zeroconf is built."""

    def __init__(self, event_bus=None, playback_backend=None, device_name=None):
        self.device_name = device_name
        self.playback_backend = playback_backend
        self.volume_manager = FakeVolumeManager()

    def get_context(self, minimal=False):
        return {"status": "idle"}

    async def stop(self):
        pass


@pytest.fixture
def stub_live_construction(monkeypatch):
    """No real backends during live speaker construction."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    import app.services as services_pkg
    import app.playback_backends.factory as factory

    def fake_backend(backend_name, device_name=None, options=None):
        return SimpleNamespace(device_name=device_name, is_connected=lambda: True,
                               ensure_connected=None, disconnect=MagicMock())

    monkeypatch.setattr(factory, "get_playback_backend_by_name", fake_backend)
    monkeypatch.setattr(services_pkg, "MediaPlayerService", FakeMediaPlayer)


@pytest.mark.asyncio
async def test_speaker_add_remove_lifecycle(monkeypatch, tmp_path, stub_live_construction):
    # CONFIG_FILE is a class attr resolved at import — patch it, not the env
    # (setenv here never reached the store and tests leaked into the real file)
    monkeypatch.setattr("app.config.config.CONFIG_FILE", str(tmp_path / "config.json"))

    await startup_event()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # add with default flag (name normalized 'Living Room' -> 'living_room')
        resp = await client.post("/api/config/speakers",
                                 json={"name": "Living Room", "backend": "chromecast", "is_default": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "added"
        assert body["speaker"]["name"] == "living_room"
        assert body["default"] == "living_room"

        # persisted on disk
        with open(tmp_path / "config.json") as fh:
            assert [s["name"] for s in json.load(fh)["speakers"]] == ["living_room"]

        # duplicate rejected
        dup = await client.post("/api/config/speakers", json={"name": "living room"})
        assert dup.status_code == 400

        # unknown backend rejected
        bad = await client.post("/api/config/speakers", json={"name": "den", "backend": "airplay"})
        assert bad.status_code == 400

        # list endpoint reflects the live registry state
        listing = await client.get("/api/config/speakers")
        assert listing.status_code == 200
        assert listing.json()["speakers"][0]["name"] == "living_room"

        # set default on unknown speaker → 404
        missing = await client.put("/api/config/speakers/ghost/default")
        assert missing.status_code == 404

        # remove → store empty, default None
        removed = await client.delete("/api/config/speakers/living_room")
        assert removed.status_code == 200
        assert removed.json()["speakers"] == []
        assert removed.json()["default"] is None
        with open(tmp_path / "config.json") as fh:
            assert json.load(fh)["speakers"] == []

        # removing again → 404
        again = await client.delete("/api/config/speakers/living_room")
        assert again.status_code == 404


@pytest.mark.asyncio
async def test_speaker_discovered_endpoint(monkeypatch, tmp_path, stub_live_construction):
    # CONFIG_FILE is a class attr resolved at import — patch it, not the env
    # (setenv here never reached the store and tests leaked into the real file)
    monkeypatch.setattr("app.config.config.CONFIG_FILE", str(tmp_path / "config.json"))
    from app.playback_backends import chromecast as cc
    monkeypatch.setattr(cc, "discover_devices", lambda timeout=None: [
        {"name": "Living Room", "model": "Nest Audio", "host": "10.0.0.5", "uuid": "u1"}])

    await startup_event()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/config/speakers/discovered")
        assert resp.status_code == 200
        devices = resp.json()["discovered"]
        assert devices[0]["store_name"] == "living_room"
        assert devices[0]["configured"] is False


@pytest.mark.asyncio
async def test_speaker_display_name_endpoint(monkeypatch, tmp_path, stub_live_construction):
    monkeypatch.setattr("app.config.config.CONFIG_FILE", str(tmp_path / "config.json"))

    await startup_event()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/config/speakers", json={"name": "living_room"})

        resp = await client.put("/api/config/speakers/living_room/display",
                                json={"display_name": "Living Room Speaker"})
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "Living Room Speaker"

        listing = await client.get("/api/config/speakers")
        assert listing.json()["speakers"][0]["display_name"] == "Living Room Speaker"

        # clearing keeps the entry, display falls back to the technical name
        cleared = await client.put("/api/config/speakers/living_room/display",
                                   json={"display_name": ""})
        assert cleared.status_code == 200
        assert cleared.json()["display_name"] == ""

        unknown = await client.put("/api/config/speakers/ghost/display",
                                   json={"display_name": "Nope"})
        assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_speakers_card_shows_display_name_and_edit_control(monkeypatch, tmp_path, initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/kiosk/system/connect/manual",
                          data={"name": "living_room", "backend": "chromecast",
                                "display_name": "Living Room Speaker"})

        page = await client.get("/kiosk/config")
        assert page.status_code == 200
        html = " ".join(page.text.split())
        assert "Living Room Speaker" in html
        assert "hx-prompt=\"Display name for living_room" in html

        # rename via the HX-Prompt header path (what the pencil button sends)
        renamed = await client.post("/kiosk/config/speakers/living_room/display",
                                    headers={"HX-Prompt": "Big Room TV"})
        assert renamed.status_code == 200
        assert "Big Room TV" in renamed.text
        with open(tmp_path / "config.json") as fh:
            persisted = json.load(fh)["speakers"][0]
        assert persisted["display_name"] == "Big Room TV"


@pytest.mark.asyncio
async def test_speakers_card_delete_removes_cc_from_store(monkeypatch, tmp_path, initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/kiosk/system/connect/add-cc", data={"name": "living_room"})
        resp = await client.post("/kiosk/config/speakers/living_room/remove")
        assert resp.status_code == 200
        assert "Removed living_room" in resp.text
        with open(tmp_path / "config.json") as fh:
            assert json.load(fh)["speakers"] == []


def _inject_esp_client(client_id="esp_test"):
    """Register an ESP control client directly in the container for
    /kiosk/configure/<id> render tests."""
    from datetime import datetime
    from app.core.service_container import get_service
    from app.services.control_clients_service import ControlClient
    svc = get_service("control_clients_service")
    svc._clients[client_id] = ControlClient(
        client_id=client_id, client_type="esp32", user_name="Test Wall",
        capabilities=["tft"], connected_at=datetime.now(),
        speaker_name="living_room",
        config={"client": {"type": "esp32", "name": "Test Wall"}},
        tft_refresh_splits=[2, 4, 8])
    return svc._clients[client_id]


@pytest.mark.asyncio
async def test_configure_page_renders_card_layout(initialized_app):
    """The tabbed configurator is gone — cards matching /kiosk/config, with
    the data-config-path contract and the raw buffer intact."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _inject_esp_client()

        page = await client.get("/kiosk/configure/esp_test")
        assert page.status_code == 200
        html = " ".join(page.text.split())
        # card idiom + a few card headings with icons
        assert 'class="card mb-3"' in html
        assert "mdi-wifi" in html and "mdi-nfc-variant" in html and "mdi-code-json" in html
        # no bootstrap tabs anymore
        assert "nav-tabs" not in html and "tab-pane" not in html
        # the functional contract survives: structured fields + raw buffer + apply
        assert 'data-config-path="wifi.ssid"' in html
        assert 'data-config-path="hardware.tft.rotate_180"' in html
        assert 'data-configure-target="raw"' in html
        assert "Apply config" in html and "Apply + Reboot" in html
        assert 'data-action="configure#apply"' in html
        # back link moved into the header
        assert "Back to clients" in html

        # 404 for unknown clients
        assert (await client.get("/kiosk/configure/nope")).status_code == 404


@pytest.mark.asyncio
async def test_configure_page_htmx_partial(initialized_app):
    """SPA navigation gets the same card layout as the partial."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _inject_esp_client()
        partial = await client.get("/kiosk/configure/esp_test",
                                   headers={"HX-Request": "true"})
        assert partial.status_code == 200
        assert 'class="card mb-3"' in partial.text
        assert 'data-configure-target="raw"' in partial.text
