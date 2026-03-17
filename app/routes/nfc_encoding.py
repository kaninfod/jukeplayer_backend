
from fastapi import APIRouter, HTTPException, Depends, Request
from app.core.service_container import get_service

router = APIRouter( prefix="/api/nfc-encoding", tags=["hardware"])


@router.post("/start")
async def start_nfc_encoding(request: Request):
    data = await request.json()
    album_id = data.get("album_id")
    if not album_id:
        raise HTTPException(status_code=400, detail="album_id is required")
    nfc_state = get_service("nfc_encoding_state")
    if nfc_state.is_active():
        raise HTTPException(status_code=409, detail="NFC encoding session already active")
    nfc_state.start(album_id)
    return {"status": "encoding_mode_enabled", "album_id": album_id}

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
