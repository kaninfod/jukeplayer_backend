"""Tests for the configuration API (/api/config)."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app, startup_event


@pytest.fixture
async def initialized_app(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_FILE", str(tmp_path / "config.json"))
    await startup_event()   # builds the service container (empty store in tmp)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.asyncio
async def test_effective_config_masks_password(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_FILE", str(tmp_path / "config.json"))

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
    monkeypatch.setenv("CONFIG_FILE", str(tmp_path / "config.json"))

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
    monkeypatch.setenv("CONFIG_FILE", str(tmp_path / "config.json"))

    await startup_event()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put("/api/config/logging", json={"level": "WARNING"})
        assert resp.status_code == 200
        assert resp.json() == {"status": "saved", "applies": "live", "level": "WARNING"}
        assert logging.getLogger().level == logging.WARNING

        bad = await client.put("/api/config/logging", json={"level": "NOPE"})
        assert bad.status_code == 400

    logging.getLogger().setLevel(logging.INFO)