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
        """Initialize connection. Registration deferred until explicit register_client message."""
        logger.info(
            f"WebSocket connection accepted | "
            f"Client IP: {self.client_ip}:{self.client_port} | "
            f"Client ID: {self.client_id[:8] if self.client_id else 'None'}... | "
            f"User-Agent: {self.user_agent}"
        )
        logger.info(f"Awaiting explicit register_client message")
    
    async def _emit_and_broadcast_response(self, event_type, event_payload, response_type, response_message):
        """Emit event and broadcast generic response message.
        
        Consolidates the common pattern used by most command handlers:
        - Emit the main event
        - Broadcast a generic response message
        - Extract result from response
        
        Args:
            event_type: EventType to emit
            event_payload: Payload for the event
            response_type: Message type for response (e.g., 'next_track_response')
            response_message: Message dict payload for response
            
        Returns:
            The result from the event emission
        """
        from app.core import event_bus, EventType, Event
        
        # Emit the main event
        result = await event_bus.aemit(Event(
            type=event_type,
            payload=event_payload
        ))
        
        # Extract result message
        result_msg = result[0] if isinstance(result, list) and result else result
        
        # # Broadcast response
        # await event_bus.aemit(Event(
        #     type=EventType.BROADCAST_GENERIC_MESSAGE,
        #     payload={
        #         "message_type": response_type,
        #         "message_payload": {**response_message, "message": str(result_msg)} if isinstance(response_message, dict) else {"status": "success", "message": str(result_msg)}
        #     }
        # ))

        await self.send_message({
            "type": response_type,
            "payload": {"status": "success", "message": str(result_msg)}
        })
        
        await event_bus.aemit(Event(
            type=EventType.TRACK_CHANGED,
            payload={}
        ))

        return result
    
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
            client_registry = get_service("client_registry")
            client_type = payload.get("client_type")
            client_name = payload.get("client_name")
            capabilities = payload.get("capabilities", [])
            device_id = payload.get("device_id")  # Device ID for hardware clients (ESP32, etc.)
            stored_client_id = payload.get("client_id")  # Client ID from previous session (browser recovery)
            
            if not client_type or not client_name:
                logger.warning("Registration missing client_type or client_name")
                await self.websocket.send_json({
                    "type": "register_response",
                    "payload": {"status": "error", "message": "Missing client_type or client_name"}
                })
                return
            
            # Create send callback for this connection
            send_callback = self.send_message
            
            # Register client - registry handles session recovery automatically
            # Pass stored_client_id so registry can look it up in _disconnected_sessions and recover within timeout
            client_info = client_registry.register(
                client_type=client_type,
                user_name=client_name,
                capabilities=capabilities,
                client_ip=self.client_ip,
                websocket=self.websocket,
                send_callback=send_callback,
                client_id=stored_client_id,
                device_id=device_id
            )
            self.registered_client_id = client_info.client_id
            self.client_id = client_info.client_id
            logger.info(f"Client {client_name} (Type: {client_type}, ID: {self.client_id}) registered")

            # If client specifies device_id, assign it to that device immediately
            if device_id:
                try:
                    device_id_normalized = device_id.lower()
                    player_instance = client_registry.get_or_create_player_instance(device_id_normalized)
                    client_registry.set_client_active_instance(self.client_id, player_instance)
                    logger.info(f"Client {client_name} (ID: {self.client_id}) assigned to device: {device_id_normalized}")
                except KeyError:
                    logger.warning(f"Device '{device_id}' not configured for client {self.client_id}")
            else:
                # No device specified - assign default device for web clients (only if not recovered)
                if client_type == "web" and stored_client_id is None:
                    # New web client, not a recovery
                    try:
                        config = get_service("config")
                        default_device_from_config = getattr(config, "DEFAULT_CHROMECAST_DEVICE", "Living Room")
                        default_device_name = default_device_from_config.lower().replace(" ", "_")
                        default_device = client_registry.get_or_create_player_instance(default_device_name)
                        client_registry.set_client_active_instance(self.client_id, default_device)
                        logger.info(f"Assigned default device '{default_device_name}' to web client {self.client_id}")
                    except Exception as e:
                        logger.warning(f"Could not assign default device to web client: {e}")
                elif client_type == "web" and stored_client_id:
                    # Recovery case - device mapping should already exist from previous session
                    device_id = client_registry.get_by_id(self.client_id)
                    logger.info(f"Web client session recovered - device context preserved")
            
            await self.websocket.send_json({
                "type": "register_response",
                "payload": {
                    "status": "success",
                    "client_id": self.client_id,
                    "device_id": device_id,
                    "message": f"Registered as {client_name}"
                }
            })

            from app.core import event_bus, EventType, Event
            result = await event_bus.aemit(Event(
                type=EventType.TRACK_CHANGED,
                payload={}
            ))


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
            
            # await self.send_message({
            #     "type": "nfc_encoding_started",
            #     "payload": {
            #         "message_type": "nfc_encoding_started",
            #         "message_payload": {
            #             "status": "started",
            #             "nfc_write_state": "started",
            #         }
            #     }
            # })
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
        """Handle play/pause toggle command."""
        try:
            from app.core import event_bus, EventType
            result = await self._emit_and_broadcast_response(
                EventType.PLAY_PAUSE,
                {"client_id": self.client_id},
                "play_pause_response",
                {"status": "success"}
            )
            logger.info(f"Play/pause toggled")
        except Exception as e:
            logger.error(f"Error handling play_pause: {e}")
            await self.send_message({
                "type": "play_pause_response",
                "payload": {"status": "error", "message": str(e)}
            })
    
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
                payload={"rfid": rfid, "client_id": getattr(self, 'client_id', None) or "ws_client"}
            ))
            
            result = await event_bus.aemit(Event(
                type=EventType.BROADCAST_GENERIC_MESSAGE,
                payload={
                    "message_type": "play_rfid_response",
                    "message_payload": {
                        "status": "success" if result else "error",
                        "message": str(result) if result else "Failed to process RFID"
                    }
                }
            ))

        except Exception as e:
            logger.error(f"Error handling play_rfid: {e}")
            await self.send_message({
                "type": "play_rfid_response",
                "payload": {"status": "error", "message": str(e)}
            })

    async def handle_play_track(self, payload):
        """Handle next track command."""
        try:
            track_index = payload.get("track_index")
            if not track_index:
                raise ValueError("Missing track_index in payload")
            
            from app.core import event_bus, EventType, Event
            result = await event_bus.aemit(Event(
                type=EventType.PLAY_TRACK,
                payload={"track_index": track_index, "client_id": self.client_id or self.client_id}
            ))

            result = await event_bus.aemit(Event(
                type=EventType.BROADCAST_GENERIC_MESSAGE,
                payload={
                    "message_type": "play_track_response",
                    "message_payload": {"status": "success", "message": str(result[0])}
                }
            ))

            logger.info(f"Play track: {result}")
        except Exception as e:
            logger.error(f"Error handling play_track: {e}")
            await self.send_message({
                "type": "play_track_response",
                "payload": {"status": "error", "message": str(e)}
            })

    async def handle_play_album(self, payload):
        """Handle play album command.
        
        Args:
            payload: Message payload with album_id and optional start_track_index
        """
        try:
            album_id = payload.get("album_id")
            
            if album_id is None:
                raise ValueError("Missing album_id")
            
            start_track_index = payload.get("start_track_index", 0)
            
            from app.core import event_bus, EventType, Event
            result = event_bus.emit(Event(
                type=EventType.PLAY_ALBUM,
                payload={
                    "album_id": album_id,
                    "start_track_index": start_track_index,
                    "client_id": self.client_id
                }
            ))

            result = await event_bus.aemit(Event(
                type=EventType.BROADCAST_GENERIC_MESSAGE,
                payload={
                    "message_type": "play_album_response",
                    "message_payload": {
                        "status": "success", 
                        "album_id": album_id, 
                        "start_track_index": start_track_index, 
                        "message": str(result)}
                }
            ))

            logger.info(f"Playing album {album_id} starting at track {start_track_index}: {result}")
        except Exception as e:
            logger.error(f"Error handling play_album: {e}")
            await self.send_message({
                "type": "play_album_response",
                "payload": {"status": "error", "message": str(e)}
            })
    
    async def handle_switch_device(self, payload):
        """Switch client to control a different device.
        
        Does NOT restart playback. Just changes which MediaPlayerService 
        instance this client controls. Future commands go to that device.
        
        Args:
            payload: {"device_id": "kitchen"} or {"device_id": "bedroom"}
                    Device names are case-insensitive.
        """
        
        client_registry = get_service("client_registry")
        client_registry.switch_device(
            device_id=payload.get("device_id"),
            client_id=self.client_id
        )

        from app.core import event_bus, EventType, Event

        result = await event_bus.aemit(Event(
            type=EventType.TRACK_CHANGED,
            payload={}
        ))

        # try:
        #     device_id = payload.get("device_id")
            
        #     if not device_id:
        #         raise ValueError("Missing device_id in payload")
            
        #     # Normalize device_id to lowercase (case-insensitive)
        #     device_id = device_id.lower()
            
        #     client_registry = get_service("client_registry")
            
        #     # Get the MediaPlayerService instance for this device
        #     # Raises KeyError if device not configured
        #     try:
        #         player_instance = client_registry.get_or_create_player_instance(device_id)
        #     except KeyError as e:
        #         # List available devices for error message
        #         available = client_registry.get_configured_devices()
        #         raise ValueError(
        #             f"Device '{device_id}' not configured. "
        #             f"Available devices: {', '.join(available) if available else 'None'}"
        #         )
            
        #     # Map this client to the new device instance
        #     client_id = self.registered_client_id or self.client_id
        #     client_registry.set_client_active_instance(client_id, player_instance)
            
        #     # Get current state of the new device
        #     device_state = player_instance.get_context()
            
        #     # Send success response with new device state
        #     await self.send_message({
        #         "type": "switch_device_response",
        #         "payload": {
        #             "status": "success",
        #             "message": f"Switched to device '{device_id}'",
        #             "device_id": device_id,
        #             "current_state": device_state
        #         }
        #     })


        #     logger.info(
        #         f"Client {client_id} switched to device '{device_id}' | "
        #         f"Active clients on {device_id}: "
        #         f"{client_registry.get_instance_active_clients(device_id)}"
        #     )
            
        # except ValueError as e:
        #     await self.send_message({
        #         "type": "switch_device_response",
        #         "payload": {
        #             "status": "error",
        #             "message": str(e)
        #         }
        #     })
        #     logger.warning(f"Device switch failed: {e}")
        # except Exception as e:
        #     await self.send_message({
        #         "type": "switch_device_response",
        #         "payload": {
        #             "status": "error",
        #             "message": f"Unexpected error: {str(e)}"
        #         }
        #     })
        #     logger.error(f"Error handling switch_device: {e}", exc_info=True)

    async def handle_next_track(self, payload):
        """Handle next track command."""
        try:
            from app.core import event_bus, EventType
            result = await self._emit_and_broadcast_response(
                EventType.NEXT_TRACK,
                {"force": True, "client_id": self.client_id},
                "next_track_response",
                {"status": "success"}
            )
            logger.info(f"Next track handled")
        except Exception as e:
            logger.error(f"Error handling next_track: {e}")
            await self.send_message({
                "type": "next_track_response",
                "payload": {"status": "error", "message": str(e)}
            })
    
    async def handle_previous_track(self, payload):
        """Handle previous track command."""
        try:
            from app.core import event_bus, EventType
            result = await self._emit_and_broadcast_response(
                EventType.PREVIOUS_TRACK,
                {"client_id": self.client_id},
                "previous_track_response",
                {"status": "success"}
            )
            logger.info(f"Previous track handled")
        except Exception as e:
            logger.error(f"Error handling previous_track: {e}")
            await self.send_message({
                "type": "previous_track_response",
                "payload": {"status": "error", "message": str(e)}
            })
    
    async def handle_stop(self, payload):
        """Handle stop command."""
        try:
            from app.core import event_bus, EventType
            result = await self._emit_and_broadcast_response(
                EventType.STOP,
                {"client_id": self.client_id},
                "stop_response",
                {"status": "success"}
            )
            logger.info(f"Stop handled")
        except Exception as e:
            logger.error(f"Error handling stop: {e}")
            await self.send_message({
                "type": "stop_response",
                "payload": {"status": "error", "message": str(e)}
            })
    
    async def handle_volume_up(self, payload):
        """Handle volume up command."""
        try:
            from app.core import event_bus, EventType
            result = await self._emit_and_broadcast_response(
                EventType.VOLUME_UP,
                {"client_id": self.client_id},
                "volume_up_response",
                {"status": "success"}
            )
            logger.info(f"Volume up handled")
        except Exception as e:
            logger.error(f"Error handling volume up: {e}")
            await self.send_message({
                "type": "volume_up_response",
                "payload": {"status": "error", "message": str(e)}
            })

    async def handle_volume_down(self, payload):
        """Handle volume down command."""
        try:
            from app.core import event_bus, EventType
            result = await self._emit_and_broadcast_response(
                EventType.VOLUME_DOWN,
                {"client_id": self.client_id},
                "volume_down_response",
                {"status": "success"}
            )
            logger.info(f"Volume down handled")
        except Exception as e:
            logger.error(f"Error handling volume down: {e}")
            await self.send_message({
                "type": "volume_down_response",
                "payload": {"status": "error", "message": str(e)}
            })

    async def handle_volume(self, payload):
        """Handle volume set command."""
        try:
            volume = payload.get("value")
            from app.core import event_bus, EventType
            result = await self._emit_and_broadcast_response(
                EventType.SET_VOLUME,
                {"volume": volume, "client_id": self.client_id},
                "volume_response",
                {"status": "success"}
            )
            logger.info(f"Volume set to {volume}")
        except Exception as e:
            logger.error(f"Error handling volume: {e}")
            await self.send_message({
                "type": "volume_response",
                "payload": {"status": "error", "message": str(e)}
            })
    
    async def handle_toggle_repeat(self, payload):
        """Handle toggle repeat command."""
        try:
            from app.core import event_bus, EventType
            result = await self._emit_and_broadcast_response(
                EventType.TOGGLE_REPEAT,
                {"client_id": self.client_id},
                "toggle_repeat_response",
                {"status": "success"}
            )
            logger.info(f"Toggle repeat handled")
        except Exception as e:
            logger.error(f"Error handling toggle repeat: {e}")
            await self.send_message({
                "type": "toggle_repeat_response",
                "payload": {"status": "error", "message": str(e)}
            })


    async def handle_volume_mute(self, payload):
        """Handle volume mute command."""
        try:
            from app.core import event_bus, EventType, Event
            result = await event_bus.aemit(Event(
                type=EventType.VOLUME_MUTE,
                payload={"client_id": self.client_id}
            ))
            is_muted = result[0]['muted'] if result and 'muted' in result[0] else None
            await event_bus.aemit(Event(
                type=EventType.BROADCAST_GENERIC_MESSAGE,
                payload={
                    "message_type": "volume_mute_response",
                    "message_payload": {"status": "success", "is_muted": is_muted}
                }
            ))
            logger.info(f"Volume mute handled")
        except Exception as e:
            logger.error(f"Error handling volume mute: {e}")
            await self.send_message({
                "type": "volume_mute_response",
                "payload": {"status": "error", "message": str(e)}
            })            


    async def handle_status(self, payload):
        """Handle status request (returns minimal data)."""
        try:
            player_service = get_service("media_player_service")
            
            # Get current status info
            status_data = player_service.get_status()
            context_data = player_service.get_context()
            
            # Build minimal response
            response_payload = {
                "status": str(status_data.get("status", "unknown")).lower(),
                "volume": int(context_data.get("volume", 0) * 100) if context_data.get("volume") else 0,
                "current_track": None,
            }
            
            # Add current track info if available
            if context_data.get("current_track"):
                track = context_data["current_track"]
                response_payload["current_track"] = {
                    "title": track.get("title", "Unknown"),
                    "artist": track.get("artist", "Unknown"),
                    "album": track.get("album", "Unknown"),
                }
            
            await self.send_message({
                "type": "status_response",
                "payload": response_payload
            })
            logger.debug(f"Status sent: {response_payload['status']}")
        except Exception as e:
            logger.error(f"Error handling status: {e}")
            await self.send_message({
                "type": "status_response",
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
                    elif msg_type == "status":
                        await self.handle_status(payload)
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
                client_registry = get_service("client_registry")
                client_registry.unregister(self.client_id)
            except Exception as e:
                logger.error(f"Error unregistering client: {e}")
    
    async def handle(self):
        """Main connection handler loop."""
        try:
            # Initial state is sent by event dispatcher after registration is complete
            # (via register_response message and subsequent track_changed events)

            # Keep connection alive - messages will be delivered by event dispatcher
            # Monitor receive_task for disconnection
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
    client_id = websocket.query_params.get("client_id", None)
    
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
