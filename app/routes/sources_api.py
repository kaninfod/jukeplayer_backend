"""The sources API — the backend-first yt phase: the OAuth device-flow
handshake, the credentials, the crate search, the collection ledger's
add/list/remove, and the same-origin cover endpoint for online albums.
The frontend surfaces come later by design; everything here is curl-able.
"""
import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.service_container import get_service
from app.music_sources.ytmusic.auth import PendingGrant

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sources", tags=["sources"])


class CredentialsBody(BaseModel):
    client_id: str
    client_secret: str


class AlbumAddBody(BaseModel):
    """The record-store gesture, in its backend form: provider + the
    provider-native id (ytmusic: an MPREb… album id or an OLAK5uy… playlist id)."""
    pid: str = "ytmusic"
    aid: str


# --- helpers ---------------------------------------------------------------------

def _store():
    return get_service("config_store")

def _ytm_cfg() -> dict:
    return (_store().section("sources") or {}).get("ytmusic") or {}


def _store_ytm_cfg(patch: dict) -> dict:
    payload = _ytm_cfg()
    payload.update(patch)
    _store().update_section("sources", {"ytmusic": payload})
    return payload


def _ytm_source():
    """The registered ytmusic source — ValueError when it isn't configured
    (no token yet), surfaced as a 400."""
    try:
        return get_service("music_sources").get("ytmusic")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _source_for(pid: str):
    try:
        return get_service("music_sources").get(pid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- the device flow ---------------------------------------------------------------

@router.post("/ytmusic/credentials")
async def ytm_credentials(body: CredentialsBody):
    """Store the user's GCP client credentials (client_id/secret of the
    'TVs and Limited Input devices' OAuth client) — step one."""
    _store_ytm_cfg({"client_id": body.client_id.strip(),
                    "client_secret": body.client_secret.strip(), "enabled": True})
    return {"ok": True, "message": "credentials stored — run the auth flow next"}


@router.post("/ytmusic/auth/start")
async def ytm_auth_start():
    """Kick off the OAuth device flow: Google returns the verification_url +
    user_code; the user opens the url on ANY browser, types the code, and
    authorizes. A background task polls until the grant (or the expiry) and
    stores the refreshable token."""
    from app.music_sources.ytmusic.auth import YTMusicAuth
    cfg = _ytm_cfg()
    if not (cfg.get("client_id") and cfg.get("client_secret")):
        raise HTTPException(status_code=400, detail="ytmusic not configured — POST /api/sources/ytmusic/credentials first")
    try:
        code = YTMusicAuth(cfg["client_id"], cfg["client_secret"]).start()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Google refused the device-flow start: {e}")

    _store_ytm_cfg({"auth_pending": {
        "device_code": code.get("device_code", ""),
        "user_code": code.get("user_code", ""),
        "verification_url": code.get("verification_url", ""),
        "interval": int(code.get("interval") or 5),
        "expires": time.time() + int(code.get("expires_in") or 900),
    }})
    _spawn_poller()
    logger.info(f"[ytm] device flow started — code {code.get('user_code')} at {code.get('verification_url')}")
    return {"verification_url": code.get("verification_url"), "user_code": code.get("user_code")}


def _spawn_poller():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_poll_device_flow())


async def _poll_device_flow():
    """Poll Google's token endpoint on the device-flow interval until the
    user grants (stored + registered-ready) or the request expires."""
    from app.music_sources.ytmusic.auth import YTMusicAuth
    while True:
        cfg = _ytm_cfg()
        pending = cfg.get("auth_pending")
        if not pending:
            return
        if time.time() > float(pending.get("expires") or 0):
            _store_ytm_cfg({"auth_pending": None})
            logger.warning("[ytm] device flow expired without a grant")
            return
        await asyncio.sleep(max(2, int(pending.get("interval") or 5)))
        cfg = _ytm_cfg()
        pending = cfg.get("auth_pending")
        if not pending:
            return
        try:
            token = YTMusicAuth(cfg["client_id"], cfg["client_secret"]).complete(pending["device_code"])
        except PendingGrant:
            continue   # google says the user hasn't finished yet — keep polling
        except ValueError as e:
            logger.warning(f"[ytm] device flow ended without a grant: {e}")
            _store_ytm_cfg({"auth_pending": None})
            return
        _store_ytm_cfg({"token": token, "auth_pending": None})
        logger.info("[ytm] authorized — refreshable token stored; restart applies the new source to the registry")
        return


@router.get("/ytmusic/auth/status")
async def ytm_auth_status():
    """The state bits only (no network probe): what the polling is doing.
    has_token only believes dictionaries that actually carry an access
    token (the wait-notice impostor lesson)."""
    cfg = _ytm_cfg()
    token = cfg.get("token") or {}
    return {"has_client_credentials": bool(cfg.get("client_id") and cfg.get("client_secret")),
            "has_token": bool(token.get("access_token")),
            "user_code": (cfg.get("auth_pending") or {}).get("user_code"),
            "verification_url": (cfg.get("auth_pending") or {}).get("verification_url"),
            "enabled": bool(cfg.get("enabled", False))}


@router.post("/ytmusic/auth/abort")
async def ytm_auth_abort():
    _store_ytm_cfg({"auth_pending": None})
    return {"ok": True}


# --- the crate ----------------------------------------------------------------------

@router.get("/ytmusic/search")
async def ytm_search(q: str):
    src = _ytm_source()
    try:
        hits = src.search(q)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ytmusic search failed: {e}")
    return {"query": q, "hits": hits}


# --- the collection ledger -----------------------------------------------------------

@router.post("/albums")
async def albums_add(body: AlbumAddBody):
    """Resolve the album against its source (one probe) and snapshot it into
    the ledger; re-adds refresh the snapshot and keep the first added_at."""
    source = _source_for(body.pid)
    try:
        album = source.load_album(body.aid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"resolve failed: {e}")
    row = get_service("album_store").add_album(
        pid=source.id, aid=body.aid, title=album.title, artist=album.artist,
        year=album.year, thumb=album.cover_url or "", track_count=len(album.tracks))
    return {"ok": True, "album": row}


@router.get("/albums")
async def albums_list(pid: Optional[str] = None):
    rows = get_service("album_store").list_albums(pid=pid)
    for r in rows:
        r["cover_url"] = f"/api/sources/cover/{r['pid']}/{r['aid']}"
        r["album_id"] = f"{r['pid']}:{r['aid']}"   # the load_from_album_id-ready id
    return {"albums": rows, "count": len(rows)}


@router.delete("/albums/{pid}/{aid}")
async def albums_remove(pid: str, aid: str):
    if not get_service("album_store").remove_album(pid, aid):
        raise HTTPException(status_code=404, detail=f"{pid}:{aid} is not in the collection")
    return {"ok": True}


# --- the same-origin cover for online albums ------------------------------------------

@router.get("/cover/{pid}/{aid}")
def sources_cover(pid: str, aid: str, size: int = 180):
    """The yt thumbs ride the CoverService cache (the kiosk CSP shows
    same-origin images only). The fetch dispatches on the id-shape —
    MPREb…/OLAK5uy… = the ytmusic provider, everything else = subsonic."""
    if pid == "subsonic":
        from app.routes.subsonic import get_cover_art  # the proven route logic, same params
        return get_cover_art(album_id=aid, size=size)
    source = _source_for(pid)
    if getattr(source, "capabilities", frozenset()) is None:
        raise HTTPException(status_code=400, detail=f"source '{pid}' has no cover art")
    try:
        get_service("cover_service").ensure_cover(aid, size)   # _fetch_art dispatches by id-shape
    except Exception as e:
        logger.warning(f"[sources] cover ensure failed for {pid}/{aid}: {e}")
    from app.music_sources.covers import CoverService
    svc = get_service("cover_service")
    paths = svc._cover_paths(aid, size)
    import os
    if os.path.exists(paths.get("webp", "")):
        return FileResponse(paths["webp"], media_type="image/webp")
    if os.path.exists(paths.get("jpg", "")):
        return FileResponse(paths["jpg"], media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="no cached cover for this album")