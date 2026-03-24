"""WebSocket handlers for media player status updates.

Sends real-time updates for track changes, volume changes, and notifications.
Clients are responsible for detecting connection loss and reconnecting.

Events are dispatched centrally via event_bus to all connected clients,
preventing the handler duplication that would occur if each connection
registered its own event handlers.
"""

import asyncio
import json
import logging
import time
from fastapi import WebSocket, WebSocketDisconnect
from app.core.service_container import get_service

logger = logging.getLogger(__name__)


class WebSocketConnection:
    """Manages a single WebSocket connection to a client.
    
    Handles:
    - Per-connection message routing and heartbeat
    - Client registration via client_registry
    - Graceful shutdown and cleanup
    
    Note: Event subscriptions are now managed centrally by the event_bus,
    not per-connection. This prevents handler duplication.
    """
    
    def __init__(self, websocket: WebSocket, client_ip: str, client_port, 
                 user_agent: str, client_id: str, get_data_fn):
        self.websocket = websocket
        self.client_ip = client_ip
        self.client_port = client_port
        self.user_agent = user_agent
        self.client_id = client_id
        self.get_data_fn = get_data_fn
        
        # Extract session token from query parameters (for web clients)
        self.session_token = websocket.query_params.get("session_token")
        
        # Connection state
        self.connection_start = time.time()
        self.handler_active = {"active": True}
        self.registered_client_id = None
        
        # Async coordination
        self.loop = asyncio.get_event_loop()
        self.ws_lock = asyncio.Lock()
        
        # Tasks
        self.heartbeat_task = None
        self.receive_task = None
    
    async def setup(self):
        """Initialize connection and auto-register web clients."""
        logger.info(
            f"WebSocket connection accepted | "
            f"Client IP: {self.client_ip}:{self.client_port} | "
            f"Session Token: {self.session_token[:8] if self.session_token else 'None'}... | "
            f"User-Agent: {self.user_agent}"
        )
        
        # Only auto-register web browsers with session tokens
        # Hardware clients and other integrations must send explicit register_client messages
        if self.session_token:
            try:
                client_registry = get_service("client_registry")
                client_info = client_registry.register(
                    client_type="web",
                    user_name=self.client_id,
                    capabilities=["websocket_status"],
                    client_ip=self.client_ip,
                    websocket=self.websocket,
                    send_callback=self.send_message,
                    session_token=self.session_token
                )
                self.registered_client_id = client_info.client_id
                logger.info(f"Web client auto-registered with ID: {self.registered_client_id}")
            except Exception as e:
                logger.error(f"Error auto-registering web client: {e}")
        else:
            logger.debug(
                f"No session token provided. Waiting for explicit register_client message. "
                f"(Hardware clients and integrations must register themselves)"
            )
    
    async def send_ping(self):
        """Send a single heartbeat ping."""
        async with self.ws_lock:
            try:
                await self.websocket.send_json({"type": "ping", "payload": {}})
            except Exception:
                pass  # Ignore ping send errors
    
    async def start_heartbeat(self):
        """Start periodic heartbeat task."""
        async def send_heartbeat():
            """Send periodic heartbeat pings to keep connection alive."""
            while self.handler_active.get("active"):
                try:
                    # Check if handler is still active before sleeping
                    for _ in range(4):  # Sleep in 5-second chunks to respond quickly to shutdown
                        if not self.handler_active.get("active"):
                            break
                        await asyncio.sleep(5)
                    
                    # Check again before sending
                    if not self.handler_active.get("active"):
                        break
                    
                    try:
                        await asyncio.wait_for(self.send_ping(), timeout=2)
                    except asyncio.TimeoutError:
                        logger.warning("Heartbeat send timed out (possible deadlock on ws_lock)")
                        break
                    except (RuntimeError, Exception) as e:
                        # Connection closed or other error - exit gracefully
                        self.handler_active["active"] = False
                        break
                except asyncio.CancelledError:
                    logger.debug("Heartbeat task cancelled")
                    break
                except Exception as e:
                    logger.debug(f"Heartbeat task exiting: {type(e).__name__}: {e}")
                    break
        
        self.heartbeat_task = asyncio.create_task(send_heartbeat())
    
    async def handle_register_client(self, payload):
        """Process client registration request.
        
        Args:
            payload: Message payload with client_type, client_name, capabilities
        """
        try:
            client_registry = get_service("client_registry")
            client_type = payload.get("client_type")
            client_name = payload.get("client_name")
            capabilities = payload.get("capabilities", [])
            
            if not client_type or not client_name:
                logger.warning("Registration missing client_type or client_name")
                await self.websocket.send_json({
                    "type": "register_response",
                    "payload": {"status": "error", "message": "Missing client_type or client_name"}
                })
                return
            
            # Create send callback for this connection
            send_callback = self.send_message
            
            client_info = client_registry.register(
                client_type=client_type,
                user_name=client_name,
                capabilities=capabilities,
                client_ip=self.client_ip,
                websocket=self.websocket,
                send_callback=send_callback
            )
            self.registered_client_id = client_info.client_id
            
            await self.websocket.send_json({
                "type": "register_response",
                "payload": {
                    "status": "success",
                    "client_id": client_info.client_id,
                    "message": f"Registered as {client_name}"
                }
            })
        except Exception as e:
            logger.error(f"Error registering client: {e}")
            await self.websocket.send_json({
                "type": "register_response",
                "payload": {"status": "error", "message": str(e)}
            })
    
    async def handle_nfc_encoding_complete(self, payload):
        """Process NFC encoding completion message.
        
        Args:
            payload: Message payload with status, uid, error_message
        """
        try:
            status = payload.get("status")
            uid = payload.get("uid")
            error_message = payload.get("error_message")
            
            nfc_state = get_service("nfc_encoding_state")
            nfc_state.set_result(status=status, uid=uid, error_message=error_message)
            logger.info(f"NFC encoding completion received: status={status}, uid={uid}")
        except Exception as e:
            logger.error(f"Error handling nfc_encoding_complete: {e}")
    
    async def receive_client_messages(self):
        """Listen for incoming messages from the client and route them."""
        try:
            while self.handler_active.get("active"):
                try:
                    data = await asyncio.wait_for(self.websocket.receive_text(), timeout=60)
                    message = json.loads(data)
                    msg_type = message.get("type")
                    payload = message.get("payload", {})
                    
                    if msg_type == "register_client":
                        await self.handle_register_client(payload)
                    elif msg_type == "nfc_encoding_complete":
                        await self.handle_nfc_encoding_complete(payload)
                    else:
                        logger.debug(f"Received unhandled message type: {msg_type}")
                
                except asyncio.TimeoutError:
                    # Timeout on receive is normal - just keep listening
                    pass
                except json.JSONDecodeError:
                    logger.warning("Received invalid JSON from client")
                except Exception as e:
                    logger.error(f"Error receiving message: {e}")
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Unexpected error in receive task: {e}")
    
    async def start_receive(self):
        """Start message receive task."""
        self.receive_task = asyncio.create_task(self.receive_client_messages())
    
    async def send_message(self, message):
        """Send a message to the client.
        
        Args:
            message: Dict to send as JSON
            
        Returns:
            True if sent successfully, False if connection closed
        """
        if not self.handler_active.get("active"):
            return False
        
        try:
            async with self.ws_lock:
                await self.websocket.send_json(message)
            return True
        except RuntimeError as e:
            # Connection closed: "Cannot call "send" once a close message has been sent"
            logger.debug(f"Send failed - connection closed: {e}")
            return False
        except Exception as e:
            logger.error(f"Send error: {type(e).__name__}: {e}")
            return False
    
    async def cleanup(self):
        """Cleanup all resources in the correct order."""
        # FIRST: Stop the handler from accepting new events
        self.handler_active["active"] = False
        
        # SECOND: Cancel all background tasks
        if self.heartbeat_task and not self.heartbeat_task.done():
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
        
        if self.receive_task and not self.receive_task.done():
            self.receive_task.cancel()
            try:
                await self.receive_task
            except asyncio.CancelledError:
                pass
        
        # THIRD: Unregister client from registry
        # This will stop event_bus from sending messages to this client
        if self.registered_client_id:
            try:
                client_registry = get_service("client_registry")
                client_registry.unregister(self.registered_client_id)
            except Exception as e:
                logger.error(f"Error unregistering client: {e}")
    
    async def handle(self):
        """Main connection handler loop."""
        try:
            # Send initial state on connection
            try:
                payload = self.get_data_fn()
                message = {"type": "current_track", "payload": payload}
                await self.send_message(message)
            except Exception as e:
                logger.error(f"Error sending initial state: {e}")

            # Keep connection alive - messages will be delivered by event dispatcher
            # Client disconnect is handled by FastAPI's WebSocketDisconnect exception
            while self.handler_active.get("active"):
                await asyncio.sleep(1)
        
        except WebSocketDisconnect:
            self._log_disconnection("disconnected")
        except asyncio.CancelledError:
            self._log_disconnection("cancelled")
            return
        except Exception as e:
            duration = time.time() - self.connection_start
            logger.error(
                f"Unexpected error in WebSocket handler | "
                f"Client IP: {self.client_ip}:{self.client_port} | "
                f"Client ID: {self.client_id} | "
                f"Duration: {duration:.1f}s | "
                f"Error: {e}",
                exc_info=True
            )
    
    def _log_disconnection(self, reason):
        """Log connection termination."""
        duration = time.time() - self.connection_start
        logger.info(
            f"WebSocket {reason} | "
            f"Client IP: {self.client_ip}:{self.client_port} | "
            f"Client ID: {self.client_id} | "
            f"Duration: {duration:.1f}s"
        )


async def websocket_status_handler(websocket: WebSocket, get_data_fn):
    """Generic WebSocket status handler.
    
    Sends messages when events occur:
    - current_track: on track change
    - volume_changed: on volume change
    - notification: on notifications
    - ping: periodic heartbeat to keep connection alive
    
    Clients are responsible for detecting connection loss and reconnecting.
    Server sends periodic pings to prevent idle timeout by routers/proxies.
    
    Events are dispatched centrally, not per-connection, to avoid handler duplication.
    
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
    
    # Create and setup connection
    conn = WebSocketConnection(websocket, client_ip, client_port, user_agent, client_id, get_data_fn)
    
    try:
        await conn.setup()
        await conn.start_heartbeat()
        await conn.start_receive()
        
        # Main handler loop
        await conn.handle()
    
    finally:
        await conn.cleanup()
