
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import config
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/output", tags=["output"])


class OutputSwitchRequest(BaseModel):
    backend: str
    device_name: Optional[str] = None


def _backend_key(backend) -> str:
    if backend is None:
        return "unknown"
    name = type(backend).__name__.lower()
    if "mpv" in name:
        return "mpv"
    if "chromecast" in name:
        return "chromecast"
    return name


@router.get("/options")
def output_options():
    return {
        "status": "ok",
        "backends": ["mpv", "chromecast"],
        "chromecast_devices": list(config.CHROMECAST_DEVICES),
        "defaults": {
            "backend": config.PLAYBACK_BACKEND,
            "chromecast_device": config.DEFAULT_CHROMECAST_DEVICE,
        },
    }


@router.get("/status")
async def output_status():
    from app.core.service_container import get_service
    from app.playback_backends.factory import get_available_output_devices


    player = get_service("media_player_service")
    backend = getattr(player, "playback_backend", None)
    devices = get_available_output_devices()

    if not backend and devices:
        return {"status": "error", "message": "No active playback backend"}

    backend_status = await backend.get_status() if hasattr(backend, "get_status") else None
    readiness = (
        backend.get_output_readiness()
        if hasattr(backend, "get_output_readiness")
        else {"ready": True, "message": "No backend-specific checks"}
    )

    backend_name = _backend_key(backend)
    connected = readiness.get("ready", True)
    if backend_name == "chromecast" and hasattr(backend, "is_connected"):
        try:
            connected = bool(backend.is_connected())
        except Exception:
            connected = False

    for device in devices:
        if device.get("backend") == backend_name and device.get("device") == getattr(backend, "device_name", None):
            device["active"] = True
        else:
            device["active"] = False

        if device.get("backend") == "mpv":
            device["icon"] = "mdi-bluetooth-audio"
        elif device.get("backend") == "chromecast":
            device["icon"] = "mdi-cast"
        else:
            device["icon"] = "mdi-cast"


    return {
        "status": "ok",
        "active_backend": backend_name,
        "active_device": getattr(backend, "device_name", None),
        "connected": connected,
        "playback_backend_ready": readiness.get("ready", True),
        "backend_status": backend_status,
        "output_readiness": readiness,
        "capabilities": {
            "runtime_switch": True,
            "chromecast_device_selection": True,
            "bluetooth_via_mpv": True,
        },
        "devices": devices,
    }


@router.get("/devices")
def output_devices():
    """
    Returns all available output devices (Chromecast and MPV/Bluetooth) as a JSON list.
    Each device: {"backend": ..., "device": ..., "name": ...}
    """
    from app.playback_backends.factory import get_available_output_devices
    return {
        "status": "ok",
        "devices": get_available_output_devices()
    }

@router.post("/switch")
async def output_switch(request: OutputSwitchRequest):
    from app.core.service_container import get_service

    player = get_service("media_player_service")

    previous_backend = _backend_key(getattr(player, "playback_backend", None))

    logger.info(
        "Switching output backend requested: backend=%s device_name=%s",
        request.backend,
        request.device_name,
    )

    result = await player.switch_playback_backend(request.backend, device_name=request.device_name)

    if result.get("status") != "ok":
        return result

    result.setdefault("previous_backend", previous_backend)
    return result
