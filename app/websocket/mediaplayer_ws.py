"""WebSocket handlers for media player status updates.

Sends real-time updates for track changes, volume changes, and notifications.
Clients are responsible for detecting connection loss and reconnecting.
"""

import asyncio
import logging
import time
from fastapi import WebSocket, WebSocketDisconnect
from app.core import event_bus, EventType

logger = logging.getLogger(__name__)


async def websocket_status_handler(websocket: WebSocket, get_data_fn):
    """Generic WebSocket status handler.
    
    Sends messages when events occur:
    - current_track: on track change
    - volume_changed: on volume change
    - notification: on notifications
    - ping: periodic heartbeat to keep connection alive
    
    Clients are responsible for detecting connection loss and reconnecting.
    Server sends periodic pings to prevent idle timeout by routers/proxies.
    
    Args:
        websocket: FastAPI WebSocket connection
        get_data_fn: Callable that returns current player data
    """
    await websocket.accept()
    
    # Extract client info
    client_ip = websocket.client.host if websocket.client else "unknown"
    client_port = websocket.client.port if websocket.client else "unknown"
    user_agent = websocket.headers.get("user-agent", "unknown")
    client_id = websocket.query_params.get("client_id", "unspecified")
    
    connection_start = time.time()
    
    logger.info(
        f"WebSocket connection accepted | "
        f"Client IP: {client_ip}:{client_port} | "
        f"Client ID: {client_id} | "
        f"User-Agent: {user_agent}"
    )
    
    q = asyncio.Queue()
    loop = asyncio.get_event_loop()
    handler_active = {"active": True}
    ws_lock = asyncio.Lock()  # Prevent concurrent sends on WebSocket
    
    async def send_ping():
        """Send a single heartbeat ping."""
        async with ws_lock:
            await websocket.send_json({"type": "ping", "payload": {}})
    
    # Create a heartbeat task to send pings every 20 seconds
    # This keeps the WebSocket connection alive and prevents Starlette from timing out
    async def send_heartbeat():
        """Send periodic heartbeat pings to keep connection alive."""
        while handler_active.get("active"):
            try:
                await asyncio.sleep(20)
                if not handler_active.get("active"):
                    break
                try:
                    await asyncio.wait_for(send_ping(), timeout=5)
                except asyncio.TimeoutError:
                    logger.warning("Heartbeat send timed out (possible deadlock on ws_lock)")
                    break
                except Exception as e:
                    logger.error(f"Heartbeat send failed {type(e).__name__}: {e}")
                    break
            except asyncio.CancelledError:
                logger.debug("Heartbeat task cancelled")
                break
            except Exception as e:
                logger.error(f"Heartbeat task error {type(e).__name__}: {e}")
                break
    
    # Start heartbeat task
    heartbeat_task = asyncio.create_task(send_heartbeat())

    # Create per-connection handlers
    handlers = make_ws_handlers(q, loop, handler_active, get_data_fn)

    # Subscribe all handlers to event bus
    for evt_type, h in handlers.items():
        event_bus.subscribe(evt_type, h)

    try:
        # Send initial state on connection
        if EventType.TRACK_CHANGED in handlers:
            handlers[EventType.TRACK_CHANGED](None)

        # Wait for messages and send them as they arrive
        # No timeout - connection stays open indefinitely
        # Server only sends messages when events occur
        # Client handles PING/PONG protocol frames automatically
        while True:
            message = await q.get()
            
            # Check if handler is still active before sending
            if not handler_active.get("active"):
                break
                
            try:
                async with ws_lock:
                    await websocket.send_json(message)
            except RuntimeError as e:
                # Connection closed: "Cannot call "send" once a close message has been sent"
                logger.debug(f"Send failed - connection closed: {e}")
                break
            except Exception as e:
                logger.error(f"Send error: {type(e).__name__}: {e}")
                break
                    
    except WebSocketDisconnect:
        duration = time.time() - connection_start
        logger.info(
            f"WebSocket disconnected | "
            f"Client IP: {client_ip}:{client_port} | "
            f"Client ID: {client_id} | "
            f"Duration: {duration:.1f}s"
        )
    except asyncio.CancelledError:
        duration = time.time() - connection_start
        logger.info(
            f"WebSocket handler cancelled | "
            f"Client IP: {client_ip}:{client_port} | "
            f"Client ID: {client_id} | "
            f"Duration: {duration:.1f}s"
        )
        return
    except Exception as e:
        duration = time.time() - connection_start
        logger.error(
            f"Unexpected error in WebSocket handler | "
            f"Client IP: {client_ip}:{client_port} | "
            f"Client ID: {client_id} | "
            f"Duration: {duration:.1f}s | "
            f"Error: {e}",
            exc_info=True
        )
    finally:
        # Stop heartbeat task
        handler_active["active"] = False
        if not heartbeat_task.done():
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # Cleanup event handlers
        for evt_type, h in handlers.items():
            try:
                event_bus.unsubscribe(evt_type, h)
            except Exception as e:
                logger.debug(f"Failed to unsubscribe handler for {evt_type}: {e}")


def make_ws_handlers(q: asyncio.Queue, loop, handler_active: dict, get_data_fn):
    """Factory for per-connection WebSocket event handlers.
    
    Args:
        q: Asyncio queue for messages
        loop: Event loop
        handler_active: Dict tracking if handler is still active
        get_data_fn: Callable to get current player data
        
    Returns:
        Dict mapping EventType to handler functions
    """
    
    def _push_message(message):
        """Push a message to the queue if handler is still active."""
        if handler_active.get("active"):
            try:
                asyncio.run_coroutine_threadsafe(q.put(message), loop)
            except Exception as e:
                logger.error(f"Failed to queue message: {e}")

    def track_handler(event):
        """Handle track change events."""
        try:
            payload = get_data_fn()
            message = {"type": "current_track", "payload": payload}
            _push_message(message)
        except Exception as e:
            logger.error(f"Error in track handler: {e}")
            _push_message({"type": "error", "payload": {"message": str(e)}})

    def volume_handler(event):
        """Handle volume change events."""
        try:
            payload = get_data_fn()
            message = {"type": "volume_changed", "payload": payload}
            _push_message(message)
        except Exception as e:
            logger.error(f"Error in volume handler: {e}")
            _push_message({"type": "error", "payload": {"message": str(e)}})

    def notification_handler(event):
        """Handle notification events."""
        try:
            payload = event.payload if event else {}
            message = {"type": "notification", "payload": payload}
            _push_message(message)
        except Exception as e:
            logger.error(f"Error in notification handler: {e}")
            _push_message({"type": "error", "payload": {"message": str(e)}})

    return {
        EventType.TRACK_CHANGED: track_handler,
        EventType.VOLUME_CHANGED: volume_handler,
        EventType.NOTIFICATION: notification_handler,
    }
