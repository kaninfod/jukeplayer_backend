from app.websocket.mediaplayer_ws import websocket_status_handler
from fastapi import APIRouter, Body, Query, WebSocket
from app.config import config
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mediaplayer", tags=["mediaplayer"])


def _default_player():
    """Resolve the MediaPlayerService of the default speaker, or None."""
    from app.core.service_container import get_service
    speakers_service = get_service("speakers_service")
    speaker = speakers_service.get_default_speaker()
    return speaker.mediaplayer if speaker else None


@router.post("/previous_track")
async def previous_track():
    from app.core import event_bus, EventType, Event
    result = await event_bus.aemit(Event(
        type=EventType.PREVIOUS_TRACK,
        payload={}
    ))

    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to go to previous track"}

@router.post("/next_track")
async def next_track():
    """Advance to the next track."""
    from app.core import event_bus, EventType, Event
    result = await event_bus.aemit(Event(
        type=EventType.NEXT_TRACK,
        payload={"force": True}
    ))

    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to advance to next track"}

@router.post("/play_track")
async def play_track(track_index: int = Body(..., embed=True)):
    """Play a specific track by index in the current playlist."""
    from app.core import event_bus, EventType, Event
    result = await event_bus.aemit(Event(
        type=EventType.PLAY_TRACK,
        payload={"track_index": track_index}
    ))

    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": f"Failed to play track at index {track_index}"}

@router.post("/play_pause")
async def play_pause():
    """Toggle playback."""
    from app.core import event_bus, EventType, Event
    result = await event_bus.aemit(Event(
        type=EventType.PLAY_PAUSE,
        payload={}
    ))

    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to toggle playback"}

@router.post("/stop")
async def stop():
    """Stop playback."""
    from app.core import event_bus, EventType, Event
    result = await event_bus.aemit(Event(
        type=EventType.STOP,
        payload={}
    ))

    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to stop playback"}

@router.post("/volume_up")
async def volume_up():
    """Increase volume."""
    from app.core import event_bus, EventType, Event
    result = await event_bus.aemit(Event(
        type=EventType.VOLUME_UP,
        payload={}
    ))

    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to increase volume"}


@router.post("/volume_down")
async def volume_down():
    """Decrease volume."""
    from app.core import event_bus, EventType, Event
    result = await event_bus.aemit(Event(
        type=EventType.VOLUME_DOWN,
        payload={}
    ))

    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to decrease volume"}


@router.post("/volume_set")
async def volume_set(volume: int = Query(..., ge=0, le=100)):
    """Set volume to an explicit level (0-100) via event bus."""
    from app.core import event_bus, EventType, Event
    result = await event_bus.aemit(Event(
        type=EventType.SET_VOLUME,
        payload={"volume": volume}
    ))

    logger.debug(f"Volume set event result: {result}")

    if result is not None:
        return {"status": "success", "volume": volume}
    else:
        return {"status": "error", "message": "Failed to set volume"}


@router.post("/volume_mute")
async def volume_mute():
    """Toggle mute on the active playback backend."""
    from app.core import event_bus, EventType, Event

    result = await event_bus.aemit(Event(
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
async def toggle_repeat_album():
    """Toggle repeat album mode in PlaybackManager."""
    from app.core import event_bus, EventType, Event
    result = await event_bus.aemit(Event(
        type=EventType.TOGGLE_REPEAT,
        payload={}
    ))

    logger.debug(f"Toggle repeat album event result: {result}")

    # aemit returns a list of handler results; the repeat mode is the first one
    if result and isinstance(result[0], bool):
        return {"status": "success", "repeat_album": result[0]}
    else:
        return {"status": "error", "message": "Failed to toggle repeat album mode"}


@router.post("/play_album_from_rfid/{rfid}")
async def play_album_from_rfid(rfid: str, client_id: str = Query(None)):
    """Play album from RFID using PlaybackManager."""
    from app.core import event_bus, EventType, Event
    result = await event_bus.aemit(Event(
        type=EventType.RFID_READ,
        payload={"rfid": rfid, "client_id": client_id}
    ))
    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to load RFID in PlaybackManager"}


@router.post("/play_album_from_albumid/{albumid}")
async def play_album_from_albumid(albumid: str, start_track_index: int = Query(0, ge=0), client_id: str = Query(None)):
    """Play album from album_id using the event bus."""
    from app.core import event_bus, EventType, Event
    result = await event_bus.aemit(Event(
        type=EventType.PLAY_ALBUM,
        payload={
            "album_id": albumid,
            "start_track_index": start_track_index,
            "client_id": client_id
        }
    ))

    if result:
        return {
            "status": "success",
            "message": f"Successfully queued album_id: {albumid} (starting at track {start_track_index})",
            "album_id": albumid,
            "start_track_index": start_track_index,
        }
    else:
        return {
            "status": "error",
            "message": f"Failed to load album_id: {albumid}"
        }


# Endpoint to get all info on the current track
@router.get("/status")
async def get_current_track_info():
    """Return the full playback context of the default speaker.

    Consumed by the Home Assistant integration's polling fallback
    (media_player.py _update_from_data expects a context dict with
    'current_track', 'status', 'volume', ...).
    """
    player = _default_player()
    if not player:
        return {"status": "error", "message": "No speakers configured"}
    return player.get_context()


# Dedicated WebSocket route for events (status + control)
wsrouter = APIRouter(prefix="/ws/mediaplayer", tags=["mediaplayer"])

@wsrouter.websocket("/events")
async def websocket_events(websocket: WebSocket):
    """WebSocket endpoint for player events and control.

    Bidirectional interface for:
    - Sending commands: {"type": "play_album", "payload": {...}}
    - Receiving status updates: {"type": "current_track", "payload": {...}}
    - Receiving notifications: {"type": "notification", "payload": {...}}

    Clients are responsible for detecting connection loss and reconnecting.
    """
    await websocket_status_handler(websocket)