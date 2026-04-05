
from __future__ import annotations

import logging

from app.config import config
from app.playback_backends.chromecast import get_chromecast_service
from app.playback_backends.mpv import get_mpv_service
from app.playback_backends.websocket import get_websocket_backend


logger = logging.getLogger(__name__)


def get_playback_backend_by_name(backend_name: str, device_name: str | None = None):
    backend = (backend_name or "chromecast").strip().lower()

    if backend == "mpv":
        logger.info("Using MPV playback backend")
        return get_mpv_service()
    
    if backend == "streaming":
        logger.info("Using WebSocket streaming playback backend")
        return get_websocket_backend()

    if backend != "chromecast":
        logger.warning("Unknown PLAYBACK_BACKEND '%s', falling back to chromecast", backend)

    logger.info("Using Chromecast playback backend")
    return get_chromecast_service(device_name or config.DEFAULT_CHROMECAST_DEVICE)


def get_playback_backend():
    return get_playback_backend_by_name(config.PLAYBACK_BACKEND)


def get_available_output_devices():
    """
    Returns a list of all available output devices (Chromecast, MPV/Bluetooth, WebSocket) for selection in UI/API.
    Each device is a dict: {"backend": ..., "device": ..., "name": ...}
    """
    devices = []
    # Chromecast devices from config
    for cc_name in (config.CHROMECAST_DEVICES or []):
        name = cc_name.strip()
        if name:
            devices.append({
                "backend": "chromecast",
                "device": name,
                "name": name
            })
    # MPV/Bluetooth device (if configured)
    bt_mac = getattr(config, "BT_SPEAKER_MAC", None)
    mpv_name = getattr(config, "MPV_DEVICE_NAME", None) or "MPV Device"
    if bt_mac:
        devices.append({
            "backend": "mpv",
            "device": mpv_name, #bt_mac,
            "name": mpv_name
        })
    # WebSocket streaming backend (always available)
    devices.append({
        "backend": "streaming",
        "device": "ESP32",
        "name": "ESP32 (Streaming)"
    })
    return devices