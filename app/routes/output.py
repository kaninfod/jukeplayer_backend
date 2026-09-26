"""Output/speaker introspection + assignment API.

- /api/output/speakers: full live picture (registry state + clients) plus the
  configured default speaker — the troubleshooting view.
- /api/output/control_clients: the registered control clients.
- /api/output/switch: testing convenience — assign a client to a speaker
  (same path as the WS switch_device), or with no client_id, make the
  speaker the system default.

Removed with the per-speaker era (single-player fossils): /status,
/devices, /options — /api/output/speakers is the full picture now, and
speaker switching happens through the broker (ASSIGN_SPEAKER), not by
re-pointing the one default player's backend.
"""
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/output", tags=["output"])


class SwitchRequest(BaseModel):
    """Assign a client to a speaker; without client_id, make the speaker the
    system default (the test-friendly "switch" from the single-player era)."""
    speaker: str
    client_id: Optional[str] = None


async def _assign(client_id: Optional[str], speaker_name: str) -> dict:
    """Assign a registered client to a speaker, or (no client_id) set the
    speaker as the system default."""
    from app.core import Event, EventType, event_bus
    from app.core.service_container import get_service

    if client_id:
        result = await event_bus.aemit(Event(
            type=EventType.ASSIGN_SPEAKER,
            payload={"client_id": client_id, "speaker_name": speaker_name},
        ))
        first = result[0] if result else None
        if isinstance(first, dict) and first.get("ok"):
            return {"status": "success",
                    "message": f"Client '{client_id}' assigned to '{first.get('speaker')}'",
                    "speaker": first.get("speaker")}
        error = first.get("error") if isinstance(first, dict) else "No handler ran for this action"
        return {"status": "error", "message": str(error)}

    manager = get_service("speaker_manager")
    try:
        entry = manager.set_default(speaker_name)
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    name = (entry or {}).get("name") or speaker_name
    return {"status": "success", "message": f"Default speaker set to '{name}'", "speaker": name}


@router.get("/speakers")
async def list_speakers():
    """All configured speakers with their live registry state — the
    troubleshooting view of the system."""
    from app.core.service_container import get_service

    ccs = get_service("control_clients_service")
    ss = get_service("speakers_service")
    speakers_info = ss.to_dict()
    default_speaker = ss.get_default_speaker()

    for speaker_name, speaker_data in speakers_info.items():
        clients = speaker_data.get("clients", [])
        if len(clients) > 0:
            clients_info = {}
            for client_id in clients:
                logger.debug(f"Fetching info for client ID: {client_id}")
                control_client = ccs.get_client(client_id)
                if control_client:
                    clients_info[client_id] = control_client.to_dict()
                else:
                    logger.warning(f"Client {client_id} listed on speaker {speaker_name} but not registered")
            speaker_data["clients"] = clients_info
            speakers_info[speaker_name] = speaker_data

    return {
        "status": "ok",
        "devices": speakers_info,
        "default_speaker": default_speaker.speaker_name if default_speaker else None,
    }


@router.get("/control_clients")
async def list_control_clients():
    """All registered control clients with their speaker info."""
    from app.core.service_container import get_service

    ccs = get_service("control_clients_service")
    ss = get_service("speakers_service")
    client_info = ccs.to_dict()
    for client_id, client_data in client_info.items():
        speaker_name = client_data.get("speaker_name")
        speaker = ss.get_speaker(speaker_name=speaker_name) if speaker_name else None
        client_data["speaker_info"] = speaker.to_dict() if speaker else None
        client_info[client_id] = client_data

    return {
        "status": "ok",
        "devices": client_info
    }


@router.post("/switch")
async def output_switch(request: SwitchRequest):
    """Testing convenience: switch playback context.

    - With client_id: assign that registered client to the named speaker
      (the same broker path the web UI's WS switch_device uses).
    - Without client_id: make the named speaker the system default.
    """
    return await _assign(request.client_id, request.speaker)