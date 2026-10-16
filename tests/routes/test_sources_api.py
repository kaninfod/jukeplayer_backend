"""The sources API routes: the device-flow handshake (mocked Google), the
ledger's add/list/remove, and the crate search — backend-first, curl-able."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException


class FakeRegistry:
    """music_sources double; raises when ytmusic isn't (yet) registered."""
    def __init__(self, ytm=None):
        self._ytm = ytm
    def get(self, pid=None):
        if pid == "ytmusic":
            if self._ytm is None:
                raise ValueError("Unknown music source 'ytmusic'")
            return self._ytm
        if pid is None or pid == "subsonic":
            from types import SimpleNamespace
            return SimpleNamespace(id="subsonic")
        raise ValueError(f"Unknown music source '{pid}'")


def patched_env(monkeypatch, tmp_path, ytm=None):
    """The real ConfigStoreService + AlbumStore (tmp) + a FakeRegistry with
    the sources section pre-seeded (enabled, creds present, no token)."""
    from app.config.store import ConfigStoreService
    from app.music_sources.collection import AlbumStore
    store = ConfigStoreService(path=str(tmp_path / "config.json"))
    store.update_section("sources", {"ytmusic": {"enabled": True, "client_id": "c", "client_secret": "s"}})
    album_store = AlbumStore(path=str(tmp_path / "collection.db"))
    services = {"config_store": store, "album_store": album_store,
                "music_sources": FakeRegistry(ytm=ytm)}
    monkeypatch.setattr("app.routes.sources_api.get_service", lambda name: services[name])
    return services


# --- credentials -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_credentials_stored_config_driven(monkeypatch, tmp_path):
    from app.routes.sources_api import ytm_credentials, CredentialsBody
    services = patched_env(monkeypatch, tmp_path)

    result = await ytm_credentials(CredentialsBody(client_id=" MY-ID ", client_secret=" MY-SEC "))

    assert result["ok"] is True
    cfg = services["config_store"].section("sources")["ytmusic"]
    assert cfg["client_id"] == "MY-ID"          # stripped
    assert cfg["enabled"] is True


# --- the device flow --------------------------------------------------------------

@pytest.mark.asyncio
async def test_auth_start_persists_pending_and_returns_codes(monkeypatch, tmp_path):
    import app.routes.sources_api as api_mod
    services = patched_env(monkeypatch, tmp_path)
    auth = MagicMock()
    auth.start.return_value = {"device_code": "DEVCODE", "user_code": "CODE-42",
                               "verification_url": "https://google.com/device",
                               "interval": 5, "expires_in": 900}
    monkeypatch.setattr(api_mod, "_spawn_poller", lambda: None)   # no poller in tests
    monkeypatch.setattr("app.music_sources.ytmusic.auth.YTMusicAuth", MagicMock(return_value=auth))

    from app.routes.sources_api import ytm_auth_start
    result = await ytm_auth_start()

    assert result["user_code"] == "CODE-42"
    assert result["verification_url"] == "https://google.com/device"
    pending = services["config_store"].section("sources")["ytmusic"]["auth_pending"]
    assert pending["device_code"] == "DEVCODE"


@pytest.mark.asyncio
async def test_auth_start_requires_credentials(monkeypatch, tmp_path):
    services = patched_env(monkeypatch, tmp_path)
    services["config_store"].update_section("sources", {"ytmusic": {"enabled": True, "client_id": "", "client_secret": ""}})

    from app.routes.sources_api import ytm_auth_start
    with pytest.raises(HTTPException) as err:
        await ytm_auth_start()
    assert err.value.status_code == 400
    assert "credentials" in err.value.detail


@pytest.mark.asyncio
async def test_poll_device_flow_grants_and_stores_token(monkeypatch, tmp_path):
    """The background poller: pending → Google granted → the token stored,
    pending cleared, ready for a restart to register the source."""
    import asyncio
    import time as time_mod
    import app.routes.sources_api as api_mod
    services = patched_env(monkeypatch, tmp_path)
    services["config_store"].update_section("sources", {
        "ytmusic": {"enabled": True, "client_id": "c", "client_secret": "s",
                    "auth_pending": {"device_code": "D", "user_code": "U",
                                     "interval": 5, "expires": time_mod.time() + 600}}})
    auth = MagicMock()
    token = {"access_token": "a", "refresh_token": "r", "expires_at": 99}
    auth.complete.return_value = token
    monkeypatch.setattr("app.music_sources.ytmusic.auth.YTMusicAuth", MagicMock(return_value=auth))
    monkeypatch.setattr(api_mod.asyncio, "sleep", AsyncMock())   # no real waiting

    await api_mod._poll_device_flow()

    cfg = services["config_store"].section("sources")["ytmusic"]
    assert cfg["token"]["refresh_token"] == "r"
    assert cfg["auth_pending"] is None


@pytest.mark.asyncio
async def test_poll_device_flow_clears_on_expiry(monkeypatch, tmp_path):
    import time as time_mod
    import app.routes.sources_api as api_mod
    services = patched_env(monkeypatch, tmp_path)
    services["config_store"].update_section("sources", {
        "ytmusic": {"enabled": True, "client_id": "c", "client_secret": "s",
                    "auth_pending": {"device_code": "D", "expires": time_mod.time() - 10}}})

    await api_mod._poll_device_flow()

    assert services["config_store"].section("sources")["ytmusic"].get("auth_pending") is None


# --- the ledger -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_albums_add_resolves_and_snapshots(monkeypatch, tmp_path):
    from app.routes.sources_api import albums_add, AlbumAddBody
    from app.music_sources.base import SourceAlbum, SourceTrack
    ytm = MagicMock()
    ytm.id = "ytmusic"
    ytm.load_album.return_value = SourceAlbum(
        album_id="ytmusic:MPREb_x", title="The Album", artist="The Artist", year="1974",
        cover_url="http://t/1",
        tracks=[SourceTrack(track_id="ytmusic:v1", title="T1", artist="The Artist", duration="100")])
    patched_env(monkeypatch, tmp_path, ytm=ytm)

    result = await albums_add(AlbumAddBody(pid="ytmusic", aid="MPREb_x"))

    assert result["ok"] is True
    row = result["album"]
    assert row["title"] == "The Album" and row["track_count"] == 1
    assert row["origin"] == "api"


@pytest.mark.asyncio
async def test_albums_add_unknown_source_is_human_refusal(monkeypatch, tmp_path):
    from app.routes.sources_api import albums_add, AlbumAddBody
    patched_env(monkeypatch, tmp_path)   # no ytm registered
    with pytest.raises(HTTPException) as err:
        await albums_add(AlbumAddBody(pid="ytmusic", aid="MPREb_x"))
    assert err.value.status_code == 400
    assert "ytmusic" in err.value.detail


@pytest.mark.asyncio
async def test_albums_list_enriches_with_cover_route_and_loadable_id(monkeypatch, tmp_path):
    from app.routes.sources_api import albums_add, AlbumAddBody, albums_list
    from app.music_sources.base import SourceAlbum, SourceTrack
    ytm = MagicMock()
    ytm.id = "ytmusic"
    ytm.load_album.return_value = SourceAlbum(
        album_id="ytmusic:MPREb_x", title="The Album", artist="The Artist", year="1974",
        tracks=[SourceTrack(track_id="ytmusic:v1", title="T1", artist="A", duration="9")])
    patched_env(monkeypatch, tmp_path, ytm=ytm)
    await albums_add(AlbumAddBody(pid="ytmusic", aid="MPREb_x"))

    listing = await albums_list()

    row = listing["albums"][0]
    assert row["cover_url"] == "/api/sources/cover/ytmusic/MPREb_x"   # same-origin, cached
    assert row["album_id"] == "ytmusic:MPREb_x"                       # → load_from_album_id-ready


@pytest.mark.asyncio
async def test_albums_remove_404_then_ok(monkeypatch, tmp_path):
    from app.routes.sources_api import albums_remove, albums_add, AlbumAddBody
    from app.music_sources.base import SourceAlbum, SourceTrack
    ytm = MagicMock()
    ytm.id = "ytmusic"
    ytm.load_album.return_value = SourceAlbum(album_id="ytmusic:MPREb_x", title="A", artist="B",
                                              tracks=[SourceTrack(track_id="ytmusic:v", title="x", artist="x", duration="3")])
    patched_env(monkeypatch, tmp_path, ytm=ytm)
    await albums_add(AlbumAddBody(pid="ytmusic", aid="MPREb_x"))

    with pytest.raises(HTTPException) as err:
        await albums_remove("ytmusic", "MPREb_ghost")
    assert err.value.status_code == 404
    ok = await albums_remove("ytmusic", "MPREb_x")
    assert ok["ok"] is True


# --- the crate ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_when_yt_not_connected_is_a_400(monkeypatch, tmp_path):
    from app.routes.sources_api import ytm_search
    patched_env(monkeypatch, tmp_path)   # no ytm → the registry refuses
    with pytest.raises(HTTPException) as err:
        await ytm_search(q="pink floyd")
    assert err.value.status_code == 400


@pytest.mark.asyncio
async def test_search_passes_through_hits(monkeypatch, tmp_path):
    from app.routes.sources_api import ytm_search
    ytm = MagicMock()
    ytm.search.return_value = [{"kind": "track", "title": "Hit"}]
    patched_env(monkeypatch, tmp_path, ytm=ytm)
    result = await ytm_search(q="anything")
    assert result["hits"] == [{"kind": "track", "title": "Hit"}]

@pytest.mark.asyncio
async def test_poller_keeps_polling_while_pending(monkeypatch, tmp_path):
    """ytmusicapi RETURNS the wait-notice instead of raising — the poller
    must treat PendingGrant as 'still typing' and keep polling; the first
    add-bug was storing that notice as the token."""
    import time as time_mod
    import app.routes.sources_api as api_mod
    services = patched_env(monkeypatch, tmp_path)
    services["config_store"].update_section("sources", {
        "ytmusic": {"enabled": True, "client_id": "c", "client_secret": "s",
                    "auth_pending": {"device_code": "D", "user_code": "U",
                                     "interval": 5, "expires": time_mod.time() + 600}}})
    auth = MagicMock()
    full = {"access_token": "a", "refresh_token": "r", "scope": "s", "token_type": "Bearer",
            "expires_at": time_mod.time() + 3600}
    auth.complete.side_effect = [api_mod.PendingGrant("authorization_pending"), full]
    monkeypatch.setattr("app.music_sources.ytmusic.auth.YTMusicAuth", MagicMock(return_value=auth))
    monkeypatch.setattr(api_mod.asyncio, "sleep", AsyncMock())

    await api_mod._poll_device_flow()

    cfg = services["config_store"].section("sources")["ytmusic"]
    assert cfg["token"]["access_token"] == "a"      # the real grant stored
    assert cfg["auth_pending"] is None


def test_pending_error_dict_is_never_accepted_as_token(monkeypatch):
    """complete() refuses the wait-notice shape (the first-add bug 2026-10-16)."""
    from app.music_sources.ytmusic.auth import YTMusicAuth, PendingGrant
    import app.music_sources.ytmusic.auth as auth_mod
    auth = YTMusicAuth.__new__(YTMusicAuth)
    auth._creds = MagicMock()
    auth._creds.token_from_code.return_value = {"error": "authorization_pending",
                                                "error_description": "Precondition Required"}
    with pytest.raises(PendingGrant):
        auth.complete("DEVCODE")
    auth._creds.token_from_code.return_value = {"access_token": "x"}   # incomplete grant
    with pytest.raises(ValueError, match="incomplete token"):
        auth.complete("DEVCODE")
