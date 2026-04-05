"""WebSocket audio streaming with time-based pacing.

Simple streaming handler that sends audio chunks at a fixed pace.
The ESP32 buffers chunks and consumes them at its own rate.
Natural backpressure: if ESP32 buffer is full, recv() blocks on the ESP32.

Benefits:
- Simple, no ACK protocol complexity
- Reliable (no socket write failures from ACK sending)
- Natural backpressure via buffer overflow
- Easy to debug and maintain
"""

import asyncio
import logging
import time
import base64
from typing import Optional, Dict, Any
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)


class AudioStreamConnection:
    """Manages time-paced audio streaming over WebSocket.
    
    Protocol: Send chunks at fixed intervals (50ms apart).
    ESP32 buffers chunks and consumes at its own rate.
    When buffer fills, recv() naturally blocks (backpressure).
    """
    
    def __init__(self, websocket: WebSocket, chunk_size: int = 4096, chunk_interval_ms: float = 50.0):
        """Initialize paced audio stream.
        
        Args:
            websocket: Audio stream WebSocket (JSON messages with base64 data)
            chunk_size: Size of each chunk to send (bytes)
            chunk_interval_ms: Milliseconds between sending chunks (roughly 128 kbps target)
        """
        self.websocket = websocket
        self.chunk_size = chunk_size
        self.chunk_interval_ms = chunk_interval_ms
        self.streaming = False
        self.chunk_id = 0
    
    async def stream_audio_url(self, url: str, track_id: str) -> bool:
        """Stream audio from HTTP URL with time-based pacing.
        
        Args:
            url: HTTP(S) URL to stream from
            track_id: Track ID for logging/correlation
            
        Returns:
            True if completed successfully, False if error
        """
        try:
            import aiohttp
            
            self.streaming = True
            self.chunk_id = 0
            bytes_sent = 0
            chunks_sent = 0
            start_time = time.time()
            
            # Send metadata
            await self.websocket.send_json({
                "type": "audio_metadata",
                "payload": {
                    "track_id": track_id,
                    "url": url,
                    "chunk_size": self.chunk_size,
                    "protocol_version": 3
                }
            })
            logger.info(f"🎵 Metadata sent: {track_id}")
            
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(
                        total=None, sock_connect=10, sock_read=10)) as resp:
                        
                        if resp.status != 200:
                            error_msg = f"HTTP {resp.status} from {url}"
                            logger.error(f"❌ {error_msg}")
                            await self._send_error(track_id, error_msg, 0)
                            return False
                        
                        logger.info(f"📡 Streaming {track_id} ({resp.content_length/1024/1024:.1f}MB)...")
                        
                        # Send chunks with fixed pacing (50ms apart)
                        try:
                            async for chunk in resp.content.iter_chunked(self.chunk_size):
                                if not self.streaming or not chunk:
                                    break
                                
                                try:
                                    # Send chunk
                                    await self._send_chunk(chunk, False)
                                    bytes_sent += len(chunk)
                                    chunks_sent += 1
                                    
                                    # Time-based pacing (instead of ACK waiting)
                                    await asyncio.sleep(self.chunk_interval_ms / 1000.0)
                                    
                                    # Log progress every 10 chunks
                                    if chunks_sent % 10 == 0:
                                        elapsed = time.time() - start_time
                                        rate_kb_s = (bytes_sent / 1024) / elapsed if elapsed > 0 else 0
                                        logger.info(f"📊 {chunks_sent} chunks, {bytes_sent/1024/1024:.1f}MB, {rate_kb_s:.1f}KB/s")
                                except (WebSocketDisconnect, BrokenPipeError, ConnectionResetError) as e:
                                    logger.warning(f"⚠️ Client disconnected during streaming: {type(e).__name__}")
                                    self.streaming = False
                                    break
                        except Exception as e:
                            logger.error(f"❌ Streaming error: {e}")
                            raise
            
            except asyncio.TimeoutError:
                error_msg = f"Timeout streaming from {url}"
                logger.error(f"❌ {error_msg}")
                await self._send_error(track_id, error_msg, self.chunk_id)
                return False
            
            # Send completion signal
            await self.websocket.send_json({
                "type": "audio_complete",
                "payload": {
                    "track_id": track_id,
                    "chunks_sent": chunks_sent,
                    "bytes_sent": bytes_sent
                }
            })
            logger.info(f"✅ Stream complete: {chunks_sent} chunks, {bytes_sent/1024/1024:.2f}MB")
            
            return True
        
        except Exception as e:
            logger.error(f"❌ Stream error: {e}", exc_info=True)
            try:
                await self._send_error(track_id, str(e), self.chunk_id)
            except Exception:
                pass
            return False
        
        finally:
            self.streaming = False
    
    async def _send_chunk(self, chunk: bytes, is_final: bool = False):
        """Send a single chunk with ID.
        
        Args:
            chunk: Binary audio data
            is_final: True if this is the last chunk
        """
        chunk_b64 = base64.b64encode(chunk).decode('ascii')
        
        await self.websocket.send_json({
            "type": "audio_chunk",
            "payload": {
                "chunk_id": self.chunk_id,
                "data": chunk_b64,
                "data_size": len(chunk),
                "is_final": is_final
            }
        })
        self.chunk_id += 1
    
    async def _send_error(self, track_id: str, error_msg: str, chunk_id: int):
        """Send error message (safe - won't crash if socket closed)."""
        try:
            await self.websocket.send_json({
                "type": "audio_error",
                "payload": {
                    "track_id": track_id,
                    "chunk_id": chunk_id,
                    "error": error_msg
                }
            })
        except Exception as e:
            logger.warning(f"Could not send error message (socket may be closed): {e}")


async def websocket_audio_stream(websocket: WebSocket):
    """WebSocket endpoint for streaming audio to ESP32/clients using ACK protocol.
    
    Uses the ACK-based protocol for better flow control and reliability.
    All messages (chunks, ACKs, events) flow over a single WebSocket connection using JSON.
    
    Message Types:
    - audio_metadata: Sent by server with track and stream info
    - audio_chunk: Sent by server with base64-encoded MP3 data and chunk_id
    - audio_ack: Sent by ESP32 with buffer fill % and status
    - audio_complete: Sent by server when stream done
    - audio_error: Sent by server on error
    """
    from app.core.service_container import get_service
    
    await websocket.accept()
    logger.info(f"🔗 WebSocket accepted at /ws/mediaplayer/audio | ID: {id(websocket)} | State: {websocket.application_state}")
    
    # Get client info from query params
    client_type = websocket.query_params.get("client_type", "unknown")
    client_name = websocket.query_params.get("client_name", "unknown")
    
    # Register this connection
    client_registry = get_service("client_registry")
    try:
        client_info = client_registry.register(
            client_type=client_type,
            user_name=client_name,
            capabilities=["audio_stream"],
            client_ip=websocket.client.host if websocket.client else "unknown",
            websocket=websocket,
            send_callback=None
        )
        registered_client_id = client_info.client_id
        logger.info(f"Audio stream client registered: {registered_client_id} ({client_type}/{client_name})")
    except Exception as e:
        logger.error(f"Failed to register audio stream client: {e}")
        registered_client_id = None
    
    # Use ACK-based connection
    conn = AudioStreamConnection(websocket)
    logger.info(f"🎙️ AudioStreamConnection created | WebSocket ID: {id(websocket)} | Conn ID: {id(conn)}")
    
    try:
        # Get the current playback context and playlist
        playback_service = get_service("playback_service")
        player = playback_service.player
        
        current_index = player.current_index
        playlist = player.playlist
        
        if not playlist or current_index < 0 or current_index >= len(playlist):
            await websocket.send_json({
                "type": "audio_stream_error",
                "payload": {"error": "No track currently loaded"}
            })
            logger.warning("Audio stream: no track in playlist")
            return
        
        # Get stream URL from current track
        current_track = playlist[current_index]
        stream_url = current_track.get("stream_url")
        track_id = current_track.get("id", "unknown")
        
        if not stream_url:
            await websocket.send_json({
                "type": "audio_stream_error",
                "payload": {"error": "Current track has no stream URL"}
            })
            logger.warning(f"Audio stream: no stream_url for track {current_index}")
            return
        
        logger.info(f"Audio stream: streaming track {current_index}/{len(playlist)}: {stream_url}")
        await conn.stream_audio_url(stream_url, track_id)
    
    except WebSocketDisconnect as e:
        logger.info(f"Audio stream client disconnected (code: {e.code}): {registered_client_id}")
        conn.streaming = False
    except Exception as e:
        logger.error(f"❌ Audio stream error ({type(e).__name__}): {e}")
        conn.streaming = False
    
    finally:
        conn.streaming = False
        # Unregister client on disconnect
        if registered_client_id:
            try:
                client_registry.unregister(registered_client_id)
                logger.info(f"Audio stream client unregistered: {registered_client_id}")
            except Exception as e:
                logger.error(f"Failed to unregister audio stream client: {e}")


__all__ = [
    'AudioStreamConnection',
    'AckRegistry',
    'websocket_audio_stream'
]
