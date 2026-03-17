from fastapi import APIRouter, HTTPException, Query
from app.services.chromecast_service import get_chromecast_service
from app.config import config
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/api/chromecast/scan")
def scan_network_devices(timeout: int = Query(None, description="Network scan timeout in seconds")):
    """
    Scan the network for available Chromecast devices.
    
    Performs a live network discovery and returns actual device information
    from the network. This is useful for troubleshooting, verification, and
    discovering new devices that may not be in the config yet.
    
    Returns:
        {
            "status": "ok",
            "scan_duration_seconds": 3,
            "devices_found": 5,
            "devices": [
                {
                    "name": "Living Room",
                    "model": "Nest Audio",
                    "host": "192.168.68.46",
                    "uuid": "uuid-string"
                },
                ...
            ]
        }
    """
    try:
        import time
        start_time = time.time()
        
        service = get_chromecast_service()
        devices = service.scan_network_for_devices(timeout=timeout)
        
        scan_duration = time.time() - start_time
        
        return {
            "status": "ok",
            "scan_duration_seconds": round(scan_duration, 2),
            "devices_found": len(devices),
            "devices": devices
        }
    except Exception as e:
        logger.error(f"Failed to scan for Chromecast devices: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to scan network: {e}")

@router.get("/api/chromecast/connect")
def chromecast_connect(
    device_name: str = Query(config.DEFAULT_CHROMECAST_DEVICE, description="Chromecast device name"),
    fallback: bool = Query(True, description="Connect to first available device if target not found")
):
    try:
        with get_chromecast_service(device_name) as service:
            success = service.connect(fallback=fallback)
            if not success or not service.cast:
                logger.warning(f"Failed to connect to Chromecast: {device_name} (fallback={fallback})")
                return {"status": "not_connected", "device": device_name}
            return {"status": "connected", "device": service.cast.name}
    except Exception as e:
        logger.error(f"Failed to connect to Chromecast: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to connect: {e}")
@router.get("/api/chromecast/status")
def chromecast_status():
    """
    Get current Chromecast status including:
    - All available devices on network
    - Currently active device (if any)
    - Active device playback status
    
    Uses the singleton to access the actual active connection state.
    """
    try:
        service = get_chromecast_service()
        
        # Get all available devices
        available_devices = service.list_chromecasts()
        
        # Get current active device - the one that is actually connected with self.cast set
        current_device = None
        current_status = None
        playback_info = {}
        
        # Check if we have an active connection
        if service.is_connected() and service.cast:
            current_device = service.cast.name
            current_status = service.get_status()
            if current_status:
                playback_info = {
                    "player_state": current_status.get("player_state", "UNKNOWN"),
                    "media_title": current_status.get("media_title"),
                    "media_artist": current_status.get("media_artist"),
                    "current_time": current_status.get("current_time"),
                    "duration": current_status.get("duration"),
                    "volume_level": current_status.get("volume_level"),
                    "volume_muted": current_status.get("volume_muted"),
                }
        
        return {
            "status": "ok",
            "available_devices": available_devices,
            "active_device": current_device,
            "connected": service.is_connected() and service.cast is not None,
            "playback": playback_info if playback_info else None
        }
    except Exception as e:
        logger.error(f"Failed to get Chromecast status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get status: {e}")


@router.post("/api/chromecast/switch")
def chromecast_switch(
    device_name: str = Query(..., description="Target Chromecast device name to switch to")
):
    """
    Seamlessly switch from current Chromecast device to a new device, resuming playback.
    
    Delegates to ChromecastService.switch_and_resume_playback() which orchestrates:
    1. Save current playback state (album_id and track index)
    2. Stop playback on current device
    3. Disconnect from current device
    4. Connect to new device
    5. Reload album and skip to saved track
    6. Resume playback on new device
    
    This is atomic - either succeeds fully or fails completely.
    Uses singleton instances to maintain shared state.
    """
    try:
        chromecast_service = get_chromecast_service()
        result = chromecast_service.switch_and_resume_playback(device_name)
        
        if result.get("status") == "error":
            raise HTTPException(status_code=503, detail=result.get("error", "Unknown error"))
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to switch Chromecast device to {device_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to switch device: {e}")
