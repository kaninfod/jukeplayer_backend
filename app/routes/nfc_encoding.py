
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field
import logging
from app.core.service_container import get_service

router = APIRouter( prefix="/api/nfc-encoding", tags=["hardware"])

logger = logging.getLogger(__name__)


class NFCEncodingRequest(BaseModel):
    """Request payload for NFC encoding start endpoint."""
    album_id: str = Field(..., description="Album ID to write to the NFC card")
    client_id: str = Field(None, description="Optional client ID - if provided, sends command to that client's WebSocket")


@router.post("/start")
async def start_nfc_encoding(request_body: NFCEncodingRequest):
    """Start NFC encoding session and send command to selected client.
    
    Payload:
    - album_id (required): Album ID string to write to block 4
    - client_id (optional): If provided, sends encode_nfc command to that client's WebSocket
    
    Returns:
    - If client_id provided: encoding_in_progress status (client runs async write)
    - If no client_id: encoding_mode_enabled (for manual/local encoding)
    """
    album_id = request_body.album_id
    client_id = request_body.client_id
    
    if not album_id:
        raise HTTPException(status_code=400, detail="album_id is required")
    
    nfc_state = get_service("nfc_encoding_state")
    
    # If a session is already active, reset it (stale session from timeout/error)
    if nfc_state.is_active():
        logger.warning("Stale NFC encoding session detected, resetting...")
        nfc_state.stop()
    
    # Start the encoding session
    nfc_state.start(album_id, client_id=client_id)
    
    # If a specific client was selected, send the encoding command
    if client_id:
        try:
            client_registry = get_service("client_registry")
            client_info = client_registry.get_by_id(client_id)
            
            if not client_info:
                nfc_state.stop()
                raise HTTPException(status_code=404, detail=f"Client {client_id} not found")
            
            if not client_info.websocket:
                nfc_state.stop()
                raise HTTPException(status_code=400, detail=f"Client {client_id} has no active WebSocket")
            
            # Send the encoding command to the client
            command = {
                "type": "encode_nfc",
                "payload": {
                    "album_id": album_id,
                    "block": 4  # Always write to block 4
                }
            }
            
            try:
                await client_info.websocket.send_json(command)
                logger.info(f"Sent encode_nfc command to client {client_id} for album {album_id}")
            except Exception as e:
                nfc_state.stop()
                raise HTTPException(status_code=500, detail=f"Failed to send command to client: {e}")
            
            # Return immediately - don't block waiting for response
            # The client will send nfc_encoding_complete via WebSocket when done
            # Frontend polls /api/nfc-encoding/status to check completion
            return {
                "status": "encoding_in_progress",
                "album_id": album_id,
                "client_id": client_id,
                "message": "Encoding command sent to client, waiting for response. Poll /api/nfc-encoding/status to check completion."
            }
        
        except HTTPException:
            raise
        except Exception as e:
            nfc_state.stop()
            logger.error(f"Error during NFC encoding setup: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Encoding error: {e}")
    else:
        # No client specified - just enable encoding mode for manual/local encoding
        return {
            "status": "encoding_mode_enabled",
            "album_id": album_id,
            "client_id": None
        }


@router.post("/stop")
def stop_nfc_encoding():
    nfc_state = get_service("nfc_encoding_state")
    if not nfc_state.is_active():
        raise HTTPException(status_code=409, detail="NFC encoding session not active")
    nfc_state.stop()
    return {"status": "encoding_mode_disabled"}


@router.get("/status")
def nfc_encoding_status():
    nfc_state = get_service("nfc_encoding_state")
    return {
        "encoding_mode": nfc_state.is_active(),
        "success": nfc_state.was_successful(),
        "last_uid": nfc_state.get_last_uid(),
        "album_id": nfc_state.get_album_id()
    }
