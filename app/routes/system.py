"""
System control routes for the jukebox.
Provides shutdown, reboot, and client management functionality.
"""
from fastapi import APIRouter, HTTPException
import logging

from typing import Dict, Any
from app.core.service_container import get_service

logger = logging.getLogger(__name__)

# --- Clean event-driven system operations ---
# Note: Event handlers are now in SystemService, not in routes
# The service listens for events and handles the operations


router = APIRouter(prefix="/api/system", tags=["system"])
@router.get("/ping")
async def ping() -> Dict[str, Any]:
    return {"status": "ok", "message": "Jukebox API is running"}



@router.get("/clients")
async def list_connected_clients() -> Dict[str, Any]:
    """
    Get list of all connected hardware clients (RPi, ESP32, etc.).
    
    Returns:
        {
            "count": 2,
            "clients": [
                {
                    "client_id": "uuid-xxx",
                    "client_type": "rpi",
                    "user_name": "living_room",
                    "capabilities": ["nfc_reader", "display"],
                    "connected_at": "2026-03-21T14:30:00"
                },
                ...
            ]
        }
    """
    try:
        client_registry = get_service("client_registry")
        clients = client_registry.get_all()
        
        return {
            "count": len(clients),
            "clients": [client.to_dict() for client in clients]
        }
    except Exception as e:
        logger.error(f"Failed to list clients: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list clients: {str(e)}"
        )


@router.get("/clients/by-capability/{capability}")
async def list_clients_by_capability(capability: str) -> Dict[str, Any]:
    """
    Get all clients with a specific capability (e.g., 'nfc_reader').
    
    Args:
        capability: The capability to filter by (e.g., 'nfc_reader', 'display')
    
    Returns:
        {
            "capability": "nfc_reader",
            "count": 1,
            "clients": [...]
        }
    """
    try:
        client_registry = get_service("client_registry")
        clients = client_registry.get_by_capability(capability)
        
        return {
            "capability": capability,
            "count": len(clients),
            "clients": [client.to_dict() for client in clients]
        }
    except Exception as e:
        logger.error(f"Failed to filter clients by capability: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to filter clients: {str(e)}"
        )


