"""HTTP transport for player actions (per-speaker routing).

Every transport endpoint accepts an optional routing context:
- client_id: the speaker the client is attached to (registered via WS)
- speaker: an explicit speaker (store) name

The broker resolves in that priority order, falling back to the
configured default speaker — which stays as the documented behavior for
manual/scripted calls with no context.

All actions return the same envelope (ActionResult); the broker's
structured results make success/failure real instead of guessed.
"""
from typing import Literal, Optional

import logging

from app.core import Event, EventType, event_bus
from app.core.service_container import get_service
from fastapi import APIRouter, Query, WebSocket
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mediaplayer", tags=["mediaplayer"])


class ActionResult(BaseModel):
    """Uniform envelope for every transport action."""
    status: Literal["success", "error"]
    message: str
    speaker: Optional[str] = None
    volume: Optional[int] = None
    muted: Optional[bool] = None
    repeat_album: Optional[bool] = None


def _envelope(result: list) -> ActionResult:
    """Wrap the first broker result in the uniform envelope.

    Handlers return {"ok": bool, "speaker": …, "volume": …, "muted": …,
    "repeat_album": …, "message": …} — anything else means the action did
    not run or failed."""
    first = result[0] if result else None
    if isinstance(first, dict) and first.get("ok"):
        return ActionResult(
            status="success",
            message=str(first.get("message") or "done"),
            speaker=first.get("speaker"),
            volume=first.get("volume"),
            muted=first.get("muted"),
            repeat_album=first.get("repeat_album"),
        )
    error = first.get("error") if isinstance(first, dict) else "No handler ran for this action"
    return ActionResult(status="error", message=str(error))


async def _run_action(event_type: EventType, *, client_id: Optional[str] = None,
                      speaker: Optional[str] = None, **payload) -> ActionResult:
    """Emit one player action with its routing context and wrap the result."""
    payload.update({"client_id": client_id, "device_name": speaker})
    result = await event_bus.aemit(Event(type=event_type, payload=payload))
    return _envelope(result)


@router.post("/play_pause", response_model=ActionResult)
async def play_pause(client_id: Optional[str] = Query(None), speaker: Optional[str] = Query(None)):
    """Toggle playback on the resolved speaker."""
    return await _run_action(EventType.PLAY_PAUSE, client_id=client_id, speaker=speaker)


@router.post("/stop", response_model=ActionResult)
async def stop(client_id: Optional[str] = Query(None), speaker: Optional[str] = Query(None)):
    """Stop playback on the resolved speaker."""
    return await _run_action(EventType.STOP, client_id=client_id, speaker=speaker)


@router.post("/next_track", response_model=ActionResult)
async def next_track(client_id: Optional[str] = Query(None), speaker: Optional[str] = Query(None)):
    """Advance to the next track on the resolved speaker."""
    return await _run_action(EventType.NEXT_TRACK, client_id=client_id, speaker=speaker, force=True)


@router.post("/previous_track", response_model=ActionResult)
async def previous_track(client_id: Optional[str] = Query(None), speaker: Optional[str] = Query(None)):
    """Go to the previous track on the resolved speaker."""
    return await _run_action(EventType.PREVIOUS_TRACK, client_id=client_id, speaker=speaker)


@router.post("/play_track", response_model=ActionResult)
async def play_track(track_index: int = Query(..., ge=0),
                     client_id: Optional[str] = Query(None),
                     speaker: Optional[str] = Query(None)):
    """Play a specific track by index in the resolved speaker's playlist."""
    return await _run_action(EventType.PLAY_TRACK, client_id=client_id, speaker=speaker,
                             track_index=track_index)


@router.post("/volume_up", response_model=ActionResult)
async def volume_up(client_id: Optional[str] = Query(None), speaker: Optional[str] = Query(None)):
    """Increase volume on the resolved speaker."""
    return await _run_action(EventType.VOLUME_UP, client_id=client_id, speaker=speaker)


@router.post("/volume_down", response_model=ActionResult)
async def volume_down(client_id: Optional[str] = Query(None), speaker: Optional[str] = Query(None)):
    """Decrease volume on the resolved speaker."""
    return await _run_action(EventType.VOLUME_DOWN, client_id=client_id, speaker=speaker)


@router.post("/volume_set", response_model=ActionResult)
async def volume_set(volume: int = Query(..., ge=0, le=100),
                     client_id: Optional[str] = Query(None),
                     speaker: Optional[str] = Query(None)):
    """Set volume to an explicit level (0-100) on the resolved speaker."""
    return await _run_action(EventType.SET_VOLUME, client_id=client_id, speaker=speaker,
                             volume=volume)


@router.post("/volume_mute", response_model=ActionResult)
async def volume_mute(client_id: Optional[str] = Query(None), speaker: Optional[str] = Query(None)):
    """Toggle mute on the resolved speaker's active playback backend."""
    return await _run_action(EventType.VOLUME_MUTE, client_id=client_id, speaker=speaker)


@router.post("/toggle_repeat_album", response_model=ActionResult)
async def toggle_repeat_album(client_id: Optional[str] = Query(None), speaker: Optional[str] = Query(None)):
    """Toggle repeat-album mode on the resolved speaker."""
    return await _run_action(EventType.TOGGLE_REPEAT, client_id=client_id, speaker=speaker)


@router.post("/play_album_from_albumid/{albumid}", response_model=ActionResult)
async def play_album_from_albumid(albumid: str,
                                  start_track_index: int = Query(0, ge=0),
                                  client_id: Optional[str] = Query(None),
                                  speaker: Optional[str] = Query(None)):
    """Play an album from its Subsonic album_id on the resolved speaker."""
    return await _run_action(EventType.PLAY_ALBUM, client_id=client_id, speaker=speaker,
                             album_id=albumid, start_track_index=start_track_index)


# Full playback context of the resolved speaker. The HA integration's
# polling fallback consumes this (media_player.py _update_from_data expects
# 'current_track', 'status', 'volume', ...).
@router.get("/status")
async def get_current_track_info(client_id: Optional[str] = Query(None),
                                 speaker: Optional[str] = Query(None)):
    """Return the full playback context of the resolved speaker.

    Resolution: the speaker attached to client_id, else the named speaker,
    else the configured default."""
    broker = get_service("speaker_broker_service")
    resolved = broker.resolve_speaker(client_id=client_id, device_name=speaker)
    if not resolved or not resolved.mediaplayer:
        return {"status": "error", "message": "No player found for the given context"}
    return resolved.mediaplayer.get_context()


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