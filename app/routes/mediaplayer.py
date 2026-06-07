
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
    """Increase volume using JukeboxMediaPlayer (master of volume, syncs to HA)."""
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
    """Decrease volume using JukeboxMediaPlayer (master of volume, syncs to HA)."""
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
    """Toggle mute on the Chromecast device."""
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

    if result is not None:
        return {"status": "success", "repeat_album": result}
    else:
        return {"status": "error", "message": "Failed to toggle repeat album mode"}


@router.get("/output_readiness")
async def output_readiness():
    """Inspect active playback backend and output readiness (including BT for MPV)."""
    try:
        from app.core.service_container import get_service

        player = get_service("media_player_service")
        backend = getattr(player, "playback_backend", None)

        if not backend:
            return {"status": "error", "message": "No playback backend available"}

        backend_name = type(backend).__name__
        status = await backend.get_status() if hasattr(backend, "get_status") else None
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


# Endpoint to trigger load_from_album_id in PlaybackManager


@router.post("/play_album_from_albumid/{albumid}")
async def play_album_from_albumid(albumid: str, start_track_index: int = Query(0, ge=0), client_id: str = Query(None)):
    """Play album from album_id using the event bus.
    
    Args:
        albumid: The album ID to play
        start_track_index: Optional track index to start playback from (default: 0)
        client_id: Optional client ID to associate with playback
    """
    try:
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
            # Query service for current track info to return
            from app.core.service_container import get_service
            payload = _get_data_for_current_track()
            
            return {
                "status": "success",
                "message": f"Successfully queued album_id: {albumid} (starting at track {start_track_index})",
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
async def get_current_track_info():
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

@router.get("/stream/current")
async def stream_current_track():
    """Proxy the current track stream directly via HTTP to ESP32."""
    from app.core.service_container import get_service
    import aiohttp
    from fastapi.responses import StreamingResponse
    from fastapi import HTTPException
    
    playback_service = get_service("playback_service")
    player = playback_service.player
    
    current_index = player.current_index
    playlist = player.playlist
    
    if not playlist or current_index < 0 or current_index >= len(playlist):
        logger.warning("[HTTP Stream] No track currently loaded")
        raise HTTPException(status_code=404, detail="No track playing")
    
    current_track = playlist[current_index]
    stream_url = current_track.get("stream_url")
    track_id = current_track.get("id", "unknown")
    
    if not stream_url:
        logger.warning(f"[HTTP Stream] No stream URL for track {track_id}")
        raise HTTPException(status_code=404, detail="No stream URL")
        
    logger.info(f"🎧 [HTTP Stream] Started for track: {track_id}")
    
    from starlette.responses import Response
    import aiohttp
    import asyncio
    
    class RawStreamingResponse(Response):
        def __init__(self, url: str):
            super().__init__()
            self.stream_url = url
            
        async def __call__(self, scope, receive, send) -> None:
            timeout = aiohttp.ClientTimeout(total=0)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.stream_url) as resp:
                    if resp.status != 200:
                        logger.error(f"[HTTP Stream] Subsonic upstream HTTP {resp.status}")
                        await send({
                            'type': 'http.response.start',
                            'status': resp.status,
                            'headers': [(b'connection', b'close')]
                        })
                        await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
                        return
                        
                    headers = [
                        (b'content-type', b'audio/mpeg'),
                        (b'connection', b'close'),
                    ]
                    
                    # Passing Content-Length disables Uvicorn/ASGI server auto-chunking
                    if 'Content-Length' in resp.headers:
                        headers.append((b'content-length', str(resp.headers['Content-Length']).encode('utf-8')))
                        
                    await send({
                        'type': 'http.response.start',
                        'status': 200,
                        'headers': headers
                    })
                    
                    try:
                        async for chunk in resp.content.iter_chunked(4096):
                            await send({
                                'type': 'http.response.body',
                                'body': chunk,
                                'more_body': True
                            })
                    except (asyncio.TimeoutError, TimeoutError):
                        logger.warning("[HTTP Stream] Upstream stream timed out")
                    except Exception as e:
                        logger.error(f"[HTTP Stream] Transfer error: {e}")
                        
            # Signal end of stream
            await send({
                'type': 'http.response.body',
                'body': b'',
                'more_body': False
            })
            
    return RawStreamingResponse(stream_url)

# ===== Phase 2: Instance & Control Management =====

@router.get("/instances")
async def list_instances():
    """List all MediaPlayerService instances and their state."""
    try:
        from app.core.service_container import get_service
        client_registry = get_service("client_registry")
        instances = client_registry.list_player_instances()
        
        result = {
            "instances": []
        }
        
        for instance in instances:
            context = instance.get_context()
            result["instances"].append({
                "device_name": instance.device_name,
                "mediaplayer_instance_name": context.get("mediaplayer_instance_name"),
                "backend_type": type(instance.playback_backend).__name__,
                "active_clients": list(instance.active_clients),
                "status": context.get("status"),
                "current_track": context.get("current_track"),
                "volume": context.get("volume"),
                "playlist_size": len(instance.playlist_manager.playlist) if hasattr(instance.playlist_manager, 'playlist') else 0
            })
        
        return result
    except Exception as e:
        logger.error(f"Failed to list instances: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/instances/{device_name}")
async def get_instance(device_name: str):
    """Get details of a specific MediaPlayerService instance."""
    try:
        from app.core.service_container import get_service
        client_registry = get_service("client_registry")
        instance = client_registry.get_player_instance(device_name)
        
        if not instance:
            return {"status": "error", "message": f"Device '{device_name}' not found"}
        
        context = instance.get_context()
        return {
            "device_name": instance.device_name,
            "backend_type": type(instance.playback_backend).__name__,
            "active_clients": list(instance.active_clients),
            "status": context.get("status"),
            "current_track": context.get("current_track"),
            "volume": context.get("volume"),
            "current_index": instance.playlist_manager.current_index if hasattr(instance.playlist_manager, 'current_index') else -1,
            "playlist": [
                {
                    "track_id": item.track_id,
                    "title": item.title,
                    "artist": item.artist,
                    "duration": item.duration
                }
                for item in (instance.playlist_manager.playlist if hasattr(instance.playlist_manager, 'playlist') else [])
            ]
        }
    except Exception as e:
        logger.error(f"Failed to get instance {device_name}: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/instances/{device_name}/control")
async def take_control(device_name: str, client_id: str = Body(..., embed=True)):
    """Client takes control of a MediaPlayerService instance (supports shared control)."""
    try:
        from app.core.service_container import get_service
        client_registry = get_service("client_registry")
        
        # Get or create instance for device
        instance = client_registry.get_or_create_player_instance(device_name)
        
        # Add client to instance's active clients
        client_registry.set_client_active_instance(client_id, instance)
        
        logger.info(f"Client {client_id} now controlling {device_name}. Active clients: {instance.active_clients}")
        
        return {
            "status": "success",
            "message": f"{client_id} now controlling {device_name}",
            "device_name": device_name,
            "active_clients": list(instance.active_clients)
        }
    except KeyError as e:
        logger.error(f"Device not configured: {device_name}")
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Failed to take control of {device_name}: {e}")
        return {"status": "error", "message": str(e)}


@router.delete("/instances/{device_name}/control")
async def release_control(device_name: str, client_id: str = Body(..., embed=True)):
    """Client releases control of a MediaPlayerService instance."""
    try:
        from app.core.service_container import get_service
        client_registry = get_service("client_registry")
        
        # Release client from instance
        client_registry.release_client_instance(client_id)
        
        # Get instance to return updated active_clients
        instance = client_registry.get_player_instance(device_name)
        active_clients = list(instance.active_clients) if instance else []
        
        logger.info(f"Client {client_id} released {device_name}. Active clients: {active_clients}")
        
        return {
            "status": "success",
            "message": f"{client_id} released {device_name}",
            "device_name": device_name,
            "active_clients": active_clients
        }
    except Exception as e:
        logger.error(f"Failed to release control of {device_name}: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/clients")
async def list_clients():
    """List all clients and their active instance mappings (introspection endpoint)."""
    try:
        from app.core.service_container import get_service
        client_registry = get_service("client_registry")
        
        return {
            "client_mappings": client_registry.list_client_instance_mappings(),
            "instance_mappings": client_registry.list_instance_client_mappings()
        }
    except Exception as e:
        logger.error(f"Failed to list clients: {e}")
        return {"status": "error", "message": str(e)}


# ===== Update Existing Endpoints to Support Client-Based Control =====

@router.post("/play_pause_v2")
async def play_pause_v2(client_id: str = Query(None)):
    """Toggle play/pause on client's active instance (v2 with client support)."""
    from app.core import event_bus, EventType, Event
    result = await event_bus.aemit(Event(
        type=EventType.PLAY_PAUSE,
        payload={"client_id": client_id}
    ))
    
    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to toggle playback"}


@router.post("/next_track_v2")
async def next_track_v2(client_id: str = Query(None)):
    """Skip to next track on client's active instance (v2 with client support)."""
    from app.core import event_bus, EventType, Event
    result = await event_bus.aemit(Event(
        type=EventType.NEXT_TRACK,
        payload={"client_id": client_id, "force": True}
    ))
    
    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to advance to next track"}


@router.post("/previous_track_v2")
async def previous_track_v2(client_id: str = Query(None)):
    """Go to previous track on client's active instance (v2 with client support)."""
    from app.core import event_bus, EventType, Event
    result = await event_bus.aemit(Event(
        type=EventType.PREVIOUS_TRACK,
        payload={"client_id": client_id}
    ))
    
    if result:
        return {"status": "success", "message": result}
    else:
        return {"status": "error", "message": "Failed to go to previous track"}


@router.post("/set_volume_v2")
async def set_volume_v2(volume: int = Query(..., ge=0, le=100), client_id: str = Query(None)):
    """Set volume on client's active instance (v2 with client support)."""
    from app.core import event_bus, EventType, Event
    result = await event_bus.aemit(Event(
        type=EventType.SET_VOLUME,
        payload={"volume": volume, "client_id": client_id}
    ))
    
    logger.debug(f"Volume set event result: {result}")
    
    if result is not None:
        return {"status": "success", "volume": volume}
    else:
        return {"status": "error", "message": "Failed to set volume"}


@router.post("/load_album_v2")
async def load_album_v2(
    album_id: str = Body(...),
    client_id: str = Body(None),
    target_device: str = Body(None),
    start_track_index: int = Body(0)
):
    """Load album to client's active instance or explicit target device (v2 with instance routing).
    
    Args:
        album_id: Album to load
        client_id: Client ID (optional) - determines device if no target_device specified
        target_device: Explicit device name (optional) - overrides client's active device
        start_track_index: Track to start from (default 0)
    """
    try:
        from app.core import event_bus, EventType, Event
        from app.core.service_container import get_service
        
        client_registry = get_service("client_registry")
        
        # Determine target device: explicit > client's device > first instance
        resolved_device = target_device
        
        if not resolved_device and client_id:
            # Get the device from client's active instance
            instance = client_registry.get_client_active_instance(client_id)
            if instance:
                resolved_device = instance.device_name
        
        if not resolved_device:
            # Fall back to first instance
            instances = client_registry.list_player_instances()
            if instances:
                resolved_device = instances[0].device_name
        
        # Emit event with resolved device
        result = await event_bus.aemit(Event(
            type=EventType.PLAY_ALBUM,
            payload={
                "album_id": album_id,
                "client_id": client_id,
                "target_device": resolved_device,
                "start_track_index": start_track_index
            }
        ))
        
        if result:
            # Get updated context
            instance = client_registry.get_player_instance(resolved_device)
            payload = instance.get_context() if instance else {}
            
            return {
                "status": "success",
                "message": f"Successfully queued album_id: {album_id}",
                "album_id": album_id,
                "device_name": instance.device_name if instance else resolved_device,
                "start_track_index": start_track_index,
                "current_track_info": payload
            }
        else:
            return {
                "status": "error", 
                "message": f"Failed to load album_id: {album_id}"
            }
    except Exception as e:
        logger.error(f"Exception while loading album_id {album_id}: {e}")
        return {
            "status": "error", 
            "message": f"Exception while loading album_id {album_id}: {str(e)}"
        }


# Dedicated WebSocket routes for events (status + control) and audio streaming
# Handlers moved to app.websocket.mediaplayer_ws and app.websocket.audio_stream for better organization

from app.websocket.mediaplayer_ws import websocket_status_handler
from app.websocket.audio_stream import websocket_audio_stream

wsrouter = APIRouter(prefix="/ws/mediaplayer", tags=["mediaplayer"])

@wsrouter.websocket("/events")
async def websocket_events(websocket: WebSocket):
    """WebSocket endpoint for player events and control.
    
    Bidirectional interface for:
    - Sending commands: {"type": "play_album", "payload": {...}}
    - Receiving status updates: {"type": "current_track", "payload": {...}}
    - Receiving notifications: {"type": "notification", "payload": {...}}
    
    Query Parameters:
    - detail=full (default): Complete player state including playlist, elapsed_time, etc.
    - detail=minimal: Minimal payload with only artist, title, album, status, volume
    
    Example URLs:
    - ws://localhost:8000/ws/mediaplayer/events?detail=full
    - ws://localhost:8000/ws/mediaplayer/events?detail=minimal&client_name=esp32-1
    
    Clients are responsible for detecting connection loss and reconnecting.
    """
    detail_level = websocket.query_params.get("detail", "full")
    
    if detail_level == "minimal":
        data_fetcher = _get_minimal_data_for_current_track
    else:
        data_fetcher = _get_data_for_current_track
    
    await websocket_status_handler(websocket, data_fetcher)


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
        "active_client": context.get("active_client"),
        "playback_backend": context.get("playback_backend"),
    }


@wsrouter.websocket("/audio")
async def ws_audio(websocket: WebSocket):
    """WebSocket endpoint for streaming binary audio to ESP32/clients.
    
    Streams raw MP3 or other audio format as binary data with client registration.
    
    Protocol:
    - Client connects with optional query params for registration
    - Server registers client for monitoring/debugging
    - Server sends audio_metadata JSON with stream info
    - Server sends binary audio chunks via send_bytes()
    - Server sends audio_stream_complete when done
    - Client unregistered on disconnect
    
    Query Parameters:
    - client_type: Device type (e.g., esp32, rpi, test)
    - client_name: Human-readable client identifier
    
    Example URLs:
    - ws://localhost:8000/ws/mediaplayer/audio?client_type=esp32&client_name=esp32-1
    - ws://localhost:8000/ws/mediaplayer/audio?client_type=test&client_name=simulator
    """
    await websocket_audio_stream(websocket)
