"""Tests for the kiosk media-library screen (/kiosk/library) — the branch
routes (search / artist / genre) and the default A-Z directory view."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app, startup_event


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def initialized_app(monkeypatch, tmp_path):
    # CONFIG_FILE is a class attr resolved at import — patch it, not the env
    monkeypatch.setattr("app.config.config.CONFIG_FILE", str(tmp_path / "config.json"))
    await startup_event()   # builds the service container (empty store in tmp)


def _stub_metadata(monkeypatch):
    """No real gonic: genres() is called on every /kiosk/library request."""
    from app.core.service_container import get_service
    amd = get_service("artist_metadata_service")
    monkeypatch.setattr(amd, "genres", lambda: [{"value": "Jazz", "albumCount": 80}])
    return amd


def _stub_subsonic(monkeypatch, **methods):
    from app.core.service_container import get_service
    svc = get_service("subsonic_service")
    for name, impl in methods.items():
        monkeypatch.setattr(svc, name, impl)
    return svc


@pytest.mark.asyncio
async def test_genre_branch_renders_album_grid_with_artist(monkeypatch, tmp_path, initialized_app):
    _stub_metadata(monkeypatch)
    _stub_subsonic(monkeypatch, list_albums_by_genre=lambda genre, limit=500: [
        {"id": "al-870", "name": "A Love Supreme", "artist": "John Coltrane",
         "year": 1965, "cover_url": ""},
    ])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/kiosk/library", params={"genre": "Jazz"})
        assert resp.status_code == 200
        html = " ".join(resp.text.split())
        assert "A Love Supreme" in html           # the grid renders
        assert "John Coltrane" in html            # artist line present on the card
        assert "data-dir-filter-open-value" not in html   # grids carry no filter bar


@pytest.mark.asyncio
async def test_default_view_shows_filter_bar_and_empty_cache_hint(monkeypatch, tmp_path, initialized_app):
    _stub_metadata(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/kiosk/library")
        assert resp.status_code == 200
        html = resp.text
        # the one-row filter bar: alpha open, the other two tucked as toggles
        assert 'data-dir-filter-open-value="alpha"' in html
        assert 'id="dir-bar-search-toggle"' in html
        assert "Refresh subsonic data" in html


@pytest.mark.asyncio
async def test_search_view_keeps_bar_open_with_the_term(monkeypatch, tmp_path, initialized_app):
    _stub_metadata(monkeypatch)
    _stub_subsonic(monkeypatch, search_artists=lambda query, count=50: [
        {"id": "al-1", "name": "Jean Michel Jarre"}])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/kiosk/library", params={"search": "Jarre"})
        assert resp.status_code == 200
        html = resp.text
        assert 'data-dir-filter-open-value="search"' in html
        assert 'data-dirfilter-results="1"' in html
        assert 'value="Jarre"' in html
        assert "Jean Michel Jarre" in html