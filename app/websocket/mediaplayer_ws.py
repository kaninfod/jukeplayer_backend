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
                 user_agent: str, client_id: str):
        self.websocket = websocket
        self.client_ip = client_ip
        self.client_port = client_port
        self.user_agent = user_agent
        self.client_id = client_id
        
        # Connection state
        self.connection_start = time.time()
        self.handler_active = {"active": True}
        
        # Async coordination
        self.loop = asyncio.get_event_loop()
        self.ws_lock = asyncio.Lock()
        
        # Tasks
        self.heartbeat_task = None
        self.receive_task = None
    
    async def setup(self):
        """Initialize connection. Registration deferred until explicit register_client message."""
        logger.info(
            f"WebSocket connection accepted | "
            f"Client IP: {self.client_ip}:{self.client_port} | "
            f"Client ID: {self.client_id[:8] if self.client_id else 'None'}... | "
            f"User-Agent: {self.user_agent}"
        )
        logger.info(f"Awaiting explicit register_client message")
    
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
                        # Heartbeat succeeded
                    except asyncio.TimeoutError:
                        # Heartbeat timed out - exit heartbeat loop
                        logger.warning("Heartbeat send timed out")
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
        """Process client registration request with session recovery support.
        
        Args:
            payload: Message payload with client_type, client_name, capabilities, device_id, client_id
        """
        try:
            client_type = payload.get("client_type")
            client_name = payload.get("client_name")
            capabilities = payload.get("capabilities", [])
            device_id = payload.get("device_id")  
            self.client_id = payload.get("client_id")

            
            if not client_type or not client_name:
                logger.warning("Registration missing client_type or client_name")
                await self.websocket.send_json({
                    "type": "register_response",
                    "payload": {"status": "error", "message": "Missing client_type or client_name"}
                })
                return
            
            # Create send callback for this connection
            send_callback = self.send_message
            
            payload = {
                "client_type": client_type,
                "user_name": client_name,
                "capabilities": capabilities,
                "client_ip": self.client_ip,
                "websocket": self.websocket,
                "send_callback": send_callback,
                "client_id": self.client_id,
                "device_name": device_id
            }

            from app.core import event_bus, EventType, Event
            result = await event_bus.aemit(Event(
                type=EventType.REGISTER_CONTROL_CLIENT,
                payload=payload
            ))
            
            logger.info(f"Client {client_name} (Type: {client_type}, ID: {self.client_id}) registered")
            
            await self.websocket.send_json({
                "type": "register_response",
                "payload": {
                    "status": "success",
                    "client_id": self.client_id,
                    "device_id": device_id,
                    "message": f"Registered as {client_name}"
                }
            })

        except Exception as e:
            logger.error(f"Error registering client: {e}")
            await self.websocket.send_json({
                "type": "register_response",
                "payload": {"status": "error", "message": str(e)}
            })
    

    async def handle_nfc_encoding_started(self, payload):
        """Process NFC encoding start message."""
        try:
            nfc_state = get_service("nfc_encoding_state")
            await nfc_state.write_in_progress()
            
        except Exception as e:
            logger.error(f"Error handling nfc_encoding_started: {e}")

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
            await nfc_state.set_result(status=status, uid=uid, error_message=error_message)

        except Exception as e:
            logger.error(f"Error handling nfc_encoding_completed: {e}")

    async def handle_nfc_encoding_cancelled(self, payload):
        """Process NFC encoding cancellation message.
        
        Args:
            payload: Message payload with status, uid, error_message
        """
        logger.info("Received nfc_encoding_cancelled message")
        try:
            nfc_state = get_service("nfc_encoding_state")
            result = nfc_state.stop()
            logger.info(f"NFC encoding cancelled")
        except Exception as e:
            logger.error(f"Error handling nfc_encoding_cancelled: {e}")
            
    async def handle_play_pause(self, payload):
        from app.core import EventType
        await self._handle_player_action(EventType.PLAY_PAUSE, payload)
    
    async def handle_play_rfid(self, payload):
        """Handle play album from RFID command."""
        try:
            rfid = payload.get("rfid")
            if not rfid:
                raise ValueError("Missing rfid in payload")
                
            from app.core import event_bus, EventType, Event
            
            logger.info(f"Received RFID read via WS: {rfid}")
            result = await event_bus.aemit(Event(
                type=EventType.RFID_READ,
                payload={"rfid": rfid, "client_id": self.client_id}
            ))

        except Exception as e:
            logger.error(f"Error handling play_rfid: {e}")
            await self.send_message({
                "type": "play_rfid_response",
                "payload": {"status": "error", "message": str(e)}
            })

    async def handle_play_track(self, payload):
        from app.core import EventType
        track_index = payload.get("track_index")
        if track_index is None:
            raise ValueError("Missing track_index in payload")
        payload={"track_index": track_index}
        await self._handle_player_action(EventType.PLAY_TRACK, payload)   

    async def handle_play_album(self, payload):
        from app.core import EventType
        album_id = payload.get("album_id")
        if album_id is None:
            raise ValueError("Missing album_id")
        start_track_index = payload.get("start_track_index", 0)
        payload={
            "album_id": album_id,
            "start_track_index": start_track_index
        }
        await self._handle_player_action(EventType.PLAY_ALBUM, payload)            
    
    async def handle_switch_device(self, payload):
        from app.core import EventType
        payload={"speaker_name": payload.get("device_id")}
        await self._handle_player_action(EventType.ASSIGN_SPEAKER, payload)

    async def handle_next_track(self, payload):
        from app.core import EventType
        await self._handle_player_action(EventType.NEXT_TRACK, payload)
    
    async def handle_previous_track(self, payload):
        from app.core import EventType
        await self._handle_player_action(EventType.PREVIOUS_TRACK, payload)
    
    async def handle_stop(self, payload):
        from app.core import EventType
        await self._handle_player_action(EventType.STOP, payload)
    
    async def handle_volume_up(self, payload):
        from app.core import EventType
        await self._handle_player_action(EventType.VOLUME_UP, payload)

    async def handle_volume_down(self, payload):
        """Handle volume down command."""
        from app.core import EventType
        await self._handle_player_action(EventType.VOLUME_DOWN, payload)

    async def handle_volume(self, payload):
        from app.core import EventType
        volume = payload.get("value")
        payload={"volume": volume}
        await self._handle_player_action(EventType.SET_VOLUME, payload)
            
    async def handle_toggle_repeat(self, payload):
        from app.core import EventType
        await self._handle_player_action(EventType.TOGGLE_REPEAT, payload)

    async def handle_volume_mute(self, payload):
        from app.core import EventType
        await self._handle_player_action(EventType.VOLUME_MUTE, payload)          

    async def _handle_player_action(self, event_type, payload):
        try:
            from app.core import event_bus, EventType, Event
            payload["client_id"] = self.client_id
            result = await event_bus.aemit(Event(
                event_type,
                payload
            ))
            logger.info(f"{event_type} handled")
        except Exception as e:
            logger.error(f"Error handling { event_type }: {e}")
            await self.send_message({
                "type": "notification",
                "payload": {"status": "error", "message": str(e)}
            })

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
                    elif msg_type == "nfc_encoding_started":
                        await self.handle_nfc_encoding_started(payload)
                    elif msg_type == "nfc_encoding_complete":
                        await self.handle_nfc_encoding_complete(payload)
                    elif msg_type == "nfc_encoding_cancelled":
                        await self.handle_nfc_encoding_cancelled(payload)                                                
                    elif msg_type in ("play_pause", "pause", "resume"):
                        await self.handle_play_pause(payload)
                    elif msg_type == "play_rfid":
                        await self.handle_play_rfid(payload)
                    elif msg_type == "play_album":
                        await self.handle_play_album(payload)
                    elif msg_type == "play_track":
                        await self.handle_play_track(payload)                     
                    elif msg_type == "next_track":
                        await self.handle_next_track(payload)
                    elif msg_type == "previous_track":
                        await self.handle_previous_track(payload)
                    elif msg_type == "stop":
                        await self.handle_stop(payload)
                    elif msg_type == "volume_mute":
                        await self.handle_volume_mute(payload)
                    elif msg_type == "volume_up":
                        await self.handle_volume_up(payload)
                    elif msg_type == "volume_down":
                        await self.handle_volume_down(payload)
                    elif msg_type == "volume":
                        await self.handle_volume(payload)
                    elif msg_type == "toggle_repeat":
                        await self.handle_toggle_repeat(payload)
                    # elif msg_type == "status":
                    #     await self.handle_status(payload)
                    elif msg_type == "switch_device":
                        await self.handle_switch_device(payload)                        
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
        if self.client_id:
            try:
                from app.core import event_bus, EventType, Event
                result = await event_bus.aemit(Event(
                    type=EventType.UNREGISTER_CONTROL_CLIENT,
                    payload={"client_id": self.client_id}
                ))

            except Exception as e:
                logger.error(f"Error unregistering client: {e}")
    
    async def handle(self):
        """Main connection handler loop."""
        try:
            while self.handler_active.get("active"):
                # Check if receive_task has completed (means connection closed)
                if self.receive_task and self.receive_task.done():
                    # Connection closed, exit handler
                    try:
                        # Get any exception from receive_task
                        self.receive_task.result()
                    except asyncio.CancelledError:
                        self._log_disconnection("receive task cancelled")
                    except Exception as e:
                        logger.debug(f"Receive task completed with error: {e}")
                    break
                
                # Sleep briefly and loop back to check receive_task
                await asyncio.sleep(0.5)
        
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


async def websocket_status_handler(websocket: WebSocket):
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
    """
    await websocket.accept()
    
    # Extract client info
    client_ip = websocket.client.host if websocket.client else "unknown"
    client_port = websocket.client.port if websocket.client else "unknown"
    user_agent = websocket.headers.get("user-agent", "unknown")
    client_id = websocket.query_params.get("client_id", "unknown")
    
    # Create and setup connection
    conn = WebSocketConnection(websocket, client_ip, client_port, user_agent, client_id)
    
    try:
        await conn.setup()
        await conn.start_heartbeat()
        await conn.start_receive()
        
        # Main handler loop
        await conn.handle()
    
    finally:
        await conn.cleanup()


# clear & uvicorn app.main:app --host 0.0.0.0 --port 8000 --env-file .env_dev
# python3 webrepl_cli.py -p jukeplay 192.168.68.54