"""Configuration API: read the effective (merged) config and update store sections."""

import logging

from fastapi import APIRouter, Body, HTTPException
from typing import Any, Dict

from app.core.service_container import get_service
from app.services.config_store import VALID_LOG_LEVELS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/config", tags=["config"])

_MASKED = "********"


def _config_service():
    return get_service("config_service")


def _store():
    return get_service("config_store")


@router.get("")
async def get_effective_config():
    """Effective configuration with per-key sources; secrets masked."""
    return _config_service().effective()


def _mask_secrets(section: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Blank secret keys are 'unchanged': never overwrite with empty/None."""
    cleaned = {}
    for key, value in (payload or {}).items():
        if (section, key) in {
            ("subsonic", "password"),
        }:
            if value in (None, "", _MASKED):
                continue  # keep existing value
            cleaned[key] = value
        else:
            cleaned[key] = value
    return cleaned


@router.put("/subsonic")
async def update_subsonic(payload: Dict[str, Any] = Body(...)):
    values = _mask_secrets("subsonic", payload)
    if "url" in values and not str(values["url"]).strip():
        raise HTTPException(status_code=400, detail="Subsonic URL cannot be empty")
    if "user" in values and not str(values["user"]).strip():
        raise HTTPException(status_code=400, detail="Subsonic user cannot be empty")
    merged = _store().update_section("subsonic", values)
    return {
        "status": "saved",
        "applies": "restart",
        "note": "Takes effect on service restart",
        "password_set": bool(merged.get("password")),
    }


@router.put("/logging")
async def update_logging(payload: Dict[str, Any] = Body(...)):
    level = str((payload or {}).get("level", "")).upper()
    if level not in VALID_LOG_LEVELS:
        raise HTTPException(status_code=400, detail=f"level must be one of {', '.join(VALID_LOG_LEVELS)}")
    _store().update_section("logging", {"level": level})
    applied = _config_service().apply_runtime()
    return {"status": "saved", "applies": "live", "level": level}


@router.put("/server")
async def update_server(payload: Dict[str, Any] = Body(...)):
    _store().update_section("server", payload or {})
    return {"status": "saved", "applies": "restart"}


# Speakers (Phase B): live-managed — add/remove applies without a restart.
# The store stays authoritative; SpeakerManagerService applies the change to
# the live registry + broker after persisting.

def _speaker_manager():
    return get_service("speaker_manager")


@router.get("/speakers")
async def list_speakers():
    manager = _speaker_manager()
    return {
        "speakers": manager.configured(),
        "default": _config_service().default_speaker_name(),
        "applies": "live",
    }


@router.get("/speakers/discovered")
async def discovered_speakers():
    """Chromecasts visible on the network (blocking mDNS scan, off the loop)."""
    import asyncio
    manager = _speaker_manager()
    devices = await asyncio.to_thread(manager.discover)
    return {"discovered": devices}


@router.post("/speakers")
async def add_speaker(payload: Dict[str, Any] = Body(...)):
    manager = _speaker_manager()
    try:
        entry = manager.add_speaker(
            name=str((payload or {}).get("name", "")),
            backend=str((payload or {}).get("backend", "chromecast")),
            options=(payload or {}).get("options"),
            is_default=bool((payload or {}).get("is_default")),
            display_name=(payload or {}).get("display_name"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "status": "added",
        "applies": "live",
        "speaker": entry,
        "speakers": manager.configured(),
        "default": _config_service().default_speaker_name(),
    }


@router.delete("/speakers/{name}")
async def remove_speaker(name: str):
    manager = _speaker_manager()
    try:
        result = await manager.remove_speaker(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "status": "removed",
        **result,
        "default": _config_service().default_speaker_name(),
    }


@router.put("/speakers/{name}/default")
async def set_default_speaker(name: str):
    manager = _speaker_manager()
    try:
        result = manager.set_default(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "saved", "applies": "live", **result}


@router.put("/speakers/{name}/display")
async def set_speaker_display_name(name: str, payload: Dict[str, Any] = Body(...)):
    """Set the UI display label for a speaker (empty string clears it)."""
    manager = _speaker_manager()
    try:
        result = manager.set_display_name(name, str((payload or {}).get("display_name", "")))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "saved", "applies": "live", **result}