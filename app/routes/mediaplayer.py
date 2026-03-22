
from fastapi import APIRouter, Body, Query, WebSocket
from app.config import config
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mediaplayer", tags=["mediaplayer"])

# def get_screen_manager():
#     from app.core.service_container import get_service
#     return get_service("screen_manager")

# Helper: build absolute URL for thumbs using PUBLIC_BASE_URL when a relative path is provided
def _abs_url(url: str):
    if not url:
        return url
    if isinstance(url, str) and (url.startswith("http://") or url.startswith("https://")):
        return url
    base = getattr(config, "PUBLIC_BASE_URL", "").rstrip("/")
    return f"{base}{url}" if base else url

@router.post("/previous_track")
def previous_track():
    from app.core import event_bus, EventType, Event
    result = event_bus.emit(Event(
        type=EventType.PREVIOUS_TRACK,
        payload={}
    ))

    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to go to previous track"}

@router.post("/next_track")
def next_track():
    """Advance to the next track."""
    from app.core import event_bus, EventType, Event
    result = event_bus.emit(Event(
        type=EventType.NEXT_TRACK,
        payload={"force": True}
    ))

    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to advance to next track"}

@router.post("/play_track")
def play_track(track_index: int = Body(..., embed=True)):
    """Play a specific track by index in the current playlist."""
    from app.core import event_bus, EventType, Event
    result = event_bus.emit(Event(
        type=EventType.PLAY_TRACK,
        payload={"track_index": track_index}
    ))

    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": f"Failed to play track at index {track_index}"}
    
@router.post("/play_pause")
def play_pause():
    """Toggle playback."""
    from app.core import event_bus, EventType, Event
    result = event_bus.emit(Event(
        type=EventType.PLAY_PAUSE,
        payload={}
    ))

    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to toggle playback"}

@router.post("/stop")
def stop():
    """Stop playback."""
    from app.core import event_bus, EventType, Event
    result = event_bus.emit(Event(
        type=EventType.STOP,
        payload={}
    ))

    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to stop playback"}



@router.post("/volume_up")
def volume_up():
    """Increase volume using JukeboxMediaPlayer (master of volume, syncs to HA)."""
    from app.core import event_bus, EventType, Event
    result = event_bus.emit(Event(
        type=EventType.VOLUME_UP,
        payload={}
    ))

    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to increase volume"}


@router.post("/volume_down")
def volume_down():
    """Decrease volume using JukeboxMediaPlayer (master of volume, syncs to HA)."""
    from app.core import event_bus, EventType, Event
    result = event_bus.emit(Event(
        type=EventType.VOLUME_DOWN,
        payload={}
    ))

    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to decrease volume"}


@router.post("/volume_set")
def volume_set(volume: int = Query(..., ge=0, le=100)):
    """Set volume to an explicit level (0-100) via event bus."""
    from app.core import event_bus, EventType, Event
    result = event_bus.emit(Event(
        type=EventType.SET_VOLUME,
        payload={"volume": volume}
    ))
    
    logger.debug(f"Volume set event result: {result}")
    
    if result is not None:
        return {"status": "success", "volume": volume}
    else:
        return {"status": "error", "message": "Failed to set volume"}


@router.post("/volume_mute")
def volume_mute():
    """Toggle mute on the Chromecast device."""
    from app.core import event_bus, EventType, Event
    
    result = event_bus.emit(Event(
        type=EventType.VOLUME_MUTE,
        payload={}
    ))
    
    logger.debug(f"Volume mute event result: {result}")
    
    if result and len(result) > 0:
        mute_result = result[0]
        if isinstance(mute_result, dict) and mute_result.get("success"):
            muted = mute_result.get("muted")
            return {
                "status": "success", 
                "message": f"Volume {'muted' if muted else 'unmuted'}",
                "muted": muted
            }
    
    return {"status": "error", "message": "Failed to toggle mute"}
    

@router.post("/toggle_repeat_album")
def toggle_repeat_album():
    """Toggle repeat album mode in PlaybackManager."""
    from app.core import event_bus, EventType, Event
    result = event_bus.emit(Event(
        type=EventType.TOGGLE_REPEAT_ALBUM,
        payload={}
    ))
    
    logger.debug(f"Toggle repeat album event result: {result}")

    if result is not None:
        return {"status": "success", "repeat_album": result}
    else:
        return {"status": "error", "message": "Failed to toggle repeat album mode"}


@router.get("/output_readiness")
def output_readiness():
    """Inspect active playback backend and output readiness (including BT for MPV)."""
    try:
        from app.core.service_container import get_service

        player = get_service("media_player_service")
        backend = getattr(player, "playback_backend", None)

        if not backend:
            return {"status": "error", "message": "No playback backend available"}

        backend_name = type(backend).__name__
        status = backend.get_status() if hasattr(backend, "get_status") else None
        readiness = (
            backend.get_output_readiness()
            if hasattr(backend, "get_output_readiness")
            else {"ready": True, "message": "No backend-specific output readiness checks"}
        )

        return {
            "status": "ok",
            "backend": backend_name,
            "device_name": getattr(backend, "device_name", None),
            "backend_status": status,
            "output_readiness": readiness,
        }
    except Exception as e:
        logger.error(f"Failed to inspect output readiness: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/play_album_from_rfid/{rfid}")
def play_album_from_rfid(rfid: str):
    """Play album from RFID using PlaybackManager."""
    from app.core import event_bus, EventType, Event
    result = event_bus.emit(Event(
        type=EventType.RFID_READ,
        payload={"rfid": rfid}
    ))
    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to load RFID in PlaybackManager"}


# Endpoint to trigger load_from_album_id in PlaybackManager


@router.post("/play_album_from_albumid/{albumid}")
def play_album_from_albumid(albumid: str, start_track_index: int = Query(0, ge=0)):
    """Play album from album_id using PlaybackManager.
    
    Args:
        albumid: The album ID to play
        start_track_index: Optional track index to start playback from (default: 0)
    """
    try:
        from app.core.service_container import get_service
        playback_service = get_service("playback_service")
        result = playback_service.load_from_album_id(albumid, start_track_index=start_track_index)
        if result:
            payload = _get_data_for_current_track()
                
            return {
                "status": "success",
                "message": f"Successfully loaded album_id: {albumid} (starting at track {start_track_index})",
                "album_id": albumid,
                "start_track_index": start_track_index,
                "current_track_info": payload
            }
        else:
            return {
                "status": "error", 
                "message": f"Failed to load album_id: {albumid}"
            }
    except Exception as e:
        logger.error(f"Exception while loading album_id {albumid}: {e}")
        return {
            "status": "error", 
            "message": f"Exception while loading album_id {albumid}: {str(e)}"
        }

# Endpoint to get all info on the current track from JukeboxMediaPlayer
@router.get("/status")
def get_current_track_info():
    """Get all info on the current track from JukeboxMediaPlayer.

    Kept function name for backwards compatibility; endpoint moved to
    /api/mediaplayer/status.
    """
    try:
        payload = _get_data_for_current_track()
        #logger.debug("status payload: %s", payload)
        return  {"type": "current_track", "payload": payload}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# Dedicated WebSocket route for current track updates (event-driven)
# Handlers moved to app.websocket.mediaplayer_ws for better organization

from app.websocket.mediaplayer_ws import websocket_status_handler

wsrouter = APIRouter(prefix="/ws/mediaplayer", tags=["mediaplayer"])

@wsrouter.websocket("/status")
async def websocket_status(websocket: WebSocket):
    """WebSocket endpoint for full player status updates.
    
    Messages sent:
    - {"type": "current_track", "payload": {...}} on track change (initial state on connect)
    - {"type": "volume_changed", "payload": {...}} on volume change
    - {"type": "notification", "payload": {...}} on notifications
    
    Full payload includes: current_track (artist, title, album, duration, year, track_id, etc.),
    status (playing/paused/idle), current_index, playlist, volume, elapsed_time, output_device.
    
    Clients are responsible for detecting connection loss and reconnecting.
    """
    await websocket_status_handler(websocket, _get_data_for_current_track)



@wsrouter.websocket("/status-minimal")
async def websocket_status_minimal(websocket: WebSocket):
    """WebSocket endpoint optimized for ESP32 microcontrollers.
    
    Messages sent:
    - {"type": "current_track", "payload": {...}} on track change (initial state on connect)
    - {"type": "volume_changed", "payload": {...}} on volume change
    - {"type": "notification", "payload": {...}} on notifications
    
    Minimal payload includes only: current_track (artist, album, title), 
    status (playing/paused/idle), volume (0-100).
    
    Clients are responsible for detecting connection loss and reconnecting.
    """
    await websocket_status_handler(websocket, _get_minimal_data_for_current_track)


def _get_data_for_current_track():
    from app.core.service_container import get_service
    playback_service = get_service("playback_service")
    player = playback_service.player 
    return player.get_context()

def _get_minimal_data_for_current_track():
    """Get minimal payload for ESP32 microcontrollers.
    
    Returns only: artist, album, current track title, player state, and volume.
    """
    from app.core.service_container import get_service
    playback_service = get_service("playback_service")
    player = playback_service.player 
    context = player.get_context()
    
    return {
        "current_track": {
            "artist": context["current_track"]["artist"],
            "title": context["current_track"]["title"],
            "album": context["current_track"]["album"],
        },
        "status": context["status"],
        "volume": context["volume"],
    }
