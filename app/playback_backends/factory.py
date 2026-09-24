
from __future__ import annotations

import logging
from typing import Dict, Optional

from app.playback_backends.chromecast import get_chromecast_service
from app.playback_backends.mpv import get_mpv_service
from app.playback_backends.websocket import get_websocket_backend

from app.core import PlayerStatus

logger = logging.getLogger(__name__)


def get_playback_backend_by_name(backend_name: str, device_name: str | None = None,
                                 options: Optional[Dict] = None):
    """Create a playback backend for a speaker. Backend-specific options come
    from the config store's speaker entry (mpv options today; chromecast
    options reserved)."""
    backend = (backend_name or "chromecast").strip().lower()

    if backend == "mpv":
        logger.info("Using MPV playback backend")
        return get_mpv_service(device_name=device_name, options=options or {})

    if backend != "chromecast":
        logger.warning("Unknown playback backend '%s', falling back to chromecast", backend)

    logger.info("Using Chromecast playback backend")
    return get_chromecast_service(device_name)


def get_playback_backend():
    """Fallback default: the first configured speaker's backend (or chromecast)."""
    from app.core.service_container import get_service
    try:
        config_service = get_service("config_service")
        speakers = config_service.speakers()
        if speakers:
            return get_playback_backend_by_name(
                speakers[0].get("backend", "chromecast"),
                device_name=speakers[0]["name"],
                options=speakers[0].get("options") or {})
    except Exception as e:
        logger.warning("Could not resolve a default backend from the store: %s", e)
    return get_chromecast_service(None)


def get_available_output_devices():
    """Configured output devices from the config store, for selection in UI/API.
    Each device: {"backend", "device", "name"}."""
    from app.core.service_container import get_service
    devices = []
    try:
        config_service = get_service("config_service")
        for entry in config_service.speakers():
            devices.append({
                "backend": entry.get("backend", "chromecast"),
                "device": entry.get("options", {}).get("device_name") or entry["name"],
                "name": entry["name"],
                "display": entry.get("display_name") or entry["name"],
            })
    except Exception as e:
        logger.warning("Could not read speakers from config store: %s", e)
    return devices


def _store_options_for(device_name: Optional[str]) -> Optional[Dict]:
    """Speaker options from the config store, for backend construction."""
    if not device_name:
        return None
    from app.core.service_container import get_service
    try:
        for entry in get_service("config_service").speakers():
            if entry["name"] == device_name.strip().lower():
                return entry.get("options") or {}
    except Exception:
        pass
    return None


async def switch_playback_backend_fac(player: "MediaPlayerService", backend: str, device_name: Optional[str] = None) -> Dict:
    #from app.services.media_player_service import MediaPlayerService
    
    previous_backend = player.playback_backend
    previous_backend_name = type(previous_backend).__name__
    previous_device = getattr(previous_backend, "device_name", None)
    previous_status = player.status
    previous_track_index = player.playlist_manager.current_index
    previous_track_id = player.playlist_manager.current_track.track_id if player.playlist_manager.current_track else None

    target_backend = (backend or "").strip().lower()
    if target_backend not in ("mpv", "chromecast", "streaming"):
        return {
            "status": "error",
            "code": "invalid_backend",
            "message": f"Unsupported backend '{backend}'",
            "rollback_applied": False,
            "previous_backend": previous_backend_name,
        }

    is_current_chromecast = "chromecast" in previous_backend_name.lower()
    is_current_streaming = "websocket" in previous_backend_name.lower() or "streaming" in previous_backend_name.lower()
    
    if is_current_chromecast:
        current_auth_backend = "chromecast"
    elif is_current_streaming:
        current_auth_backend = "streaming"
    else:
        current_auth_backend = "mpv"

    requested_device = (device_name or "").strip() or None

    # Fast no-op when backend and device are already active.
    if target_backend == current_auth_backend:
        if target_backend == "chromecast":
            if not requested_device or requested_device == previous_device:
                return {
                    "status": "ok",
                    "backend": "chromecast",
                    "device_name": previous_device,
                    "resumed": previous_status == PlayerStatus.PLAY,
                    "track_index": previous_track_index,
                    "track_id": previous_track_id,
                    "rollback_applied": False,
                    "previous_backend": previous_backend_name,
                    "previous_device": previous_device,
                }
        else:
            return {
                "status": "ok",
                "backend": target_backend,
                "device_name": getattr(previous_backend, "device_name", None),
                "resumed": previous_status == PlayerStatus.PLAY,
                "track_index": previous_track_index,
                "track_id": previous_track_id,
                "rollback_applied": False,
                "previous_backend": previous_backend_name,
                "previous_device": previous_device,
            }

    # Same-backend Chromecast device switch must reconnect immediately.
    if target_backend == "chromecast" and is_current_chromecast and requested_device and requested_device != previous_device:
        # We defer to the universal cross-backend logic below
        logger.info("Preparing to switch identical Chromecast backends with different target models.")

    try:
        previous_muted_state = None
        try:
            previous_muted_state = await previous_backend.get_volume_muted()
        except Exception:
            previous_muted_state = None

        if previous_status in (PlayerStatus.PLAY, PlayerStatus.PAUSE):
            try:
                await previous_backend.stop()
            except Exception:
                pass
        
        if "chromecast" in previous_backend_name.lower() and (target_backend != "chromecast" or (requested_device and requested_device != previous_device)):
            try:
                if hasattr(previous_backend, "disconnect"):
                    logger.info("Disconnecting from old Chromecast device: %s", previous_device)
                    previous_backend.disconnect()
            except Exception as dc_error:
                logger.warning("Failed to cleanly disconnect from previous Chromecast: %s", dc_error)

        new_backend = get_playback_backend_by_name(target_backend, device_name=requested_device,
                                                   options=_store_options_for(requested_device))
        player.playback_backend = new_backend
        player.volume_manager.playback_backend = new_backend

        backend_volume = player.volume_manager.volume / 100.0
        await player.playback_backend.set_volume(backend_volume)

        if previous_muted_state is not None:
            await player.playback_backend.set_volume_muted(bool(previous_muted_state))

        resumed = False
        if player.playlist_manager and 0 <= player.playlist_manager.current_index < player.playlist_manager.count():
            if previous_status == PlayerStatus.PLAY:
                await player.play_current_track()
                resumed = player.status == PlayerStatus.PLAY
            elif previous_status == PlayerStatus.PAUSE:
                await player.play_current_track()
                await player.playback_backend.pause()
                player.track_timer.pause()
                player.status = PlayerStatus.PAUSE
                player.emit_update()

        return {
            "status": "ok",
            "backend": target_backend,
            "device_name": getattr(player.playback_backend, "device_name", None),
            "resumed": resumed,
            "track_index": previous_track_index,
            "track_id": previous_track_id,
            "rollback_applied": False,
            "previous_backend": previous_backend_name,
            "previous_device": previous_device,
        }
    except Exception as e:
        logger.error("Failed to switch playback backend to %s: %s", target_backend, e)
        player.playback_backend = previous_backend
        player.volume_manager.playback_backend = previous_backend

        rollback_applied = False
        try:
            if previous_status == PlayerStatus.PLAY and player.playlist_manager and 0 <= player.playlist_manager.current_index < player.playlist_manager.count():
                await player.play_current_track()
                rollback_applied = player.status == PlayerStatus.PLAY
            elif previous_status == PlayerStatus.PAUSE and player.playlist_manager and 0 <= player.playlist_manager.current_index < player.playlist_manager.count():
                await player.play_current_track()
                await player.playback_backend.pause()
                player.track_timer.pause()
                player.status = PlayerStatus.PAUSE
                player.emit_update()
                rollback_applied = True
        except Exception:
            rollback_applied = False

        return {
            "status": "error",
            "code": "switch_failed",
            "message": str(e),
            "rollback_applied": rollback_applied,
            "previous_backend": previous_backend_name,
            "previous_device": previous_device,
        }