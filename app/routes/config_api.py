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

# Speakers: read-only in Phase A (live management arrives in Phase B).
# The store schema already reserves the section; the UI shows the list.