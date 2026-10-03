"""Tests for the now-playing page (/kiosk/player) — the current-speaker
card and the speakers map the live re-dressing reads."""
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app, startup_event


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def initialized_app(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.config.CONFIG_FILE", str(tmp_path / "config.json"))
    await startup_event()


@pytest.mark.asyncio
async def test_player_page_carries_speakers_card_and_map(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get("/kiosk/player")
        assert page.status_code == 200
        html = page.text
        assert "np-speaker-card" in html
        assert "data-nowplaying-speakers-map" in html

        # the card's map attr: single-quoted (JSON's double quotes must not
        # terminate the attribute), parses as JSON even with an empty registry
        raw = html.split('data-nowplaying-speakers-map=', 1)[1]
        assert raw.startswith("'")
        parsed = json.loads(raw[1:raw.index("'", 1)])
        assert parsed == {}

        # meta row: type badge + clients count line
        assert 'data-nowplaying-target="speakerclients"' in html

        # the status chip keeps its cast icon; the name lives in the span
        assert 'data-nowplaying-target="currentdevice"' in html


@pytest.mark.asyncio
async def test_player_partial_htmx_variants_carry_the_card(initialized_app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        partial = await client.get("/kiosk/player", headers={"HX-Request": "true"})
        assert partial.status_code == 200
        assert "np-speaker-card" in partial.text