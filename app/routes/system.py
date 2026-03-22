"""
System control routes for the jukebox.
Provides shutdown, reboot, and client management functionality.
"""
from fastapi import APIRouter, HTTPException
import logging
import subprocess
import asyncio
import time
import os
from typing import Dict, Any, List
from app.config import config
from app.core import EventType, Event, event_bus
from app.core.service_container import get_service

logger = logging.getLogger(__name__)

# --- Clean event-driven system operations ---
# Note: Event handlers are now in SystemService, not in routes
# The service listens for events and handles the operations


router = APIRouter(prefix="/api/system", tags=["system"])
@router.get("/ping")
async def ping() -> Dict[str, Any]:
    return {"status": "ok", "message": "Jukebox API is running"}

@router.get("/restart/status")
async def restart_status() -> Dict[str, Any]:
    """
    Check if a restart is currently pending.
    """
    from app.services import system_service
    
    is_pending = system_service.is_restart_pending()
    
    return {
        "restart_pending": is_pending,
        "message": "Restart is pending" if is_pending else "No restart pending"
    }

@router.post("/restart")
async def restart_system() -> Dict[str, str]:
    """
    Restart the jukebox service using event-driven approach.
    This restarts only the jukebox service, not the entire system.
    """
    try:
        # Emit restart event with API request context
        event = Event(
            type=EventType.SYSTEM_RESTART_REQUESTED,
            payload={"reason": "api_request", "source": "rest_api"}
        )
        
        logger.info("Emitting SYSTEM_RESTART_REQUESTED event from API endpoint")
        event_bus.emit(event)
        
        return {
            "status": "success", 
            "message": "Jukebox service restart requested via event bus (will execute within 1 minute)"
        }
        
    except Exception as e:
        logger.error(f"Failed to emit restart event: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to request restart: {str(e)}"
        )

@router.delete("/restart")
async def cancel_restart() -> Dict[str, str]:
    """
    Cancel a pending restart using event-driven approach.
    Emits SYSTEM_RESTART_CANCELLED event which is handled by the system service.
    """
    try:
        # Emit restart cancellation event
        event = Event(
            type=EventType.SYSTEM_RESTART_CANCELLED,
            payload={"source": "rest_api"}
        )
        
        logger.info("Emitting SYSTEM_RESTART_CANCELLED event from API endpoint")
        event_bus.emit(event)
        
        return {
            "status": "success", 
            "message": "Restart cancellation requested via event bus"
        }
        
    except Exception as e:
        logger.error(f"Failed to emit restart cancellation event: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to cancel restart: {str(e)}"
        )

@router.get("/reboot/status")
async def reboot_status() -> Dict[str, Any]:
    """
    Check if a reboot is currently pending.
    """
    from app.services import system_service
    
    is_pending = system_service.is_reboot_pending()
    
    return {
        "reboot_pending": is_pending,
        "message": "Reboot is pending" if is_pending else "No reboot pending"
    }

@router.post("/reboot")
async def reboot_system() -> Dict[str, str]:
    """
    Reboot the Raspberry Pi system using event-driven approach.
    Emits SYSTEM_REBOOT_REQUESTED event which is handled by the system service.
    """
    try:
        # Emit reboot event with API request context
        event = Event(
            type=EventType.SYSTEM_REBOOT_REQUESTED,
            payload={"reason": "api_request", "source": "rest_api"}
        )
        
        logger.info("Emitting SYSTEM_REBOOT_REQUESTED event from API endpoint")
        event_bus.emit(event)
        
        return {
            "status": "success", 
            "message": "System reboot requested via event bus (will execute within 1 minute)"
        }
        
    except Exception as e:
        logger.error(f"Failed to emit reboot event: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to request reboot: {str(e)}"
        )

@router.delete("/reboot")
async def cancel_reboot() -> Dict[str, str]:
    """
    Cancel a pending reboot using event-driven approach.
    Emits SYSTEM_REBOOT_CANCELLED event which is handled by the system service.
    """
    try:
        # Emit reboot cancellation event
        event = Event(
            type=EventType.SYSTEM_REBOOT_CANCELLED,
            payload={"source": "rest_api"}
        )
        
        logger.info("Emitting SYSTEM_REBOOT_CANCELLED event from API endpoint")
        event_bus.emit(event)
        
        return {
            "status": "success", 
            "message": "Reboot cancellation requested via event bus"
        }
        
    except Exception as e:
        logger.error(f"Failed to emit reboot cancellation event: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to cancel reboot: {str(e)}"
        )

@router.get("/shutdown/status")
async def shutdown_status() -> Dict[str, Any]:
    """
    Check if a shutdown is currently pending.
    """
    from app.services import system_service
    
    is_pending = system_service.is_shutdown_pending()
    
    return {
        "shutdown_pending": is_pending,
        "message": "Shutdown is pending" if is_pending else "No shutdown pending"
    }

@router.post("/shutdown")
async def shutdown_system() -> Dict[str, str]:
    """
    Shutdown the Raspberry Pi system using event-driven approach.
    Emits SYSTEM_SHUTDOWN_REQUESTED event which is handled by the system service.
    """
    try:
        # Emit shutdown event with API request context
        event = Event(
            type=EventType.SYSTEM_SHUTDOWN_REQUESTED,
            payload={"reason": "api_request", "source": "rest_api"}
        )
        
        logger.info("Emitting SYSTEM_SHUTDOWN_REQUESTED event from API endpoint")
        event_bus.emit(event)
        
        return {
            "status": "success", 
            "message": "System shutdown requested via event bus (will execute within 1 minute)"
        }
        
    except Exception as e:
        logger.error(f"Failed to emit shutdown event: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to request shutdown: {str(e)}"
        )

@router.delete("/shutdown")
async def cancel_shutdown() -> Dict[str, str]:
    """
    Cancel a pending shutdown using event-driven approach.
    Emits SYSTEM_SHUTDOWN_CANCELLED event which is handled by the system service.
    """
    try:
        # Emit shutdown cancellation event
        event = Event(
            type=EventType.SYSTEM_SHUTDOWN_CANCELLED,
            payload={"source": "rest_api"}
        )
        
        logger.info("Emitting SYSTEM_SHUTDOWN_CANCELLED event from API endpoint")
        event_bus.emit(event)
        
        return {
            "status": "success", 
            "message": "Shutdown cancellation requested via event bus"
        }
        
    except Exception as e:
        logger.error(f"Failed to emit shutdown cancellation event: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to cancel shutdown: {str(e)}"
        )


# --- Client Management ---

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


