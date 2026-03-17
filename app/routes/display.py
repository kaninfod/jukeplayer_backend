"""
API routes for display/screen brightness control.
"""

from fastapi import APIRouter, Query
import logging

logger = logging.getLogger(__name__)
router = APIRouter( prefix="/api/display", tags=["hardware"])


@router.get("/brightness")
def get_brightness():
    """Get current display brightness."""
    try:
        from app.core.service_container import get_service
        display_service = get_service("display_service")
        
        if not display_service.is_available():
            return {
                "status": "error",
                "message": "Display device not available"
            }
        
        return {
            "status": "success",
            "brightness": display_service.get_brightness(),
            "brightness_percent": display_service.get_brightness_percent(),
            "max_brightness": display_service.get_max_brightness()
        }
    except Exception as e:
        logger.error(f"Error getting brightness: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


@router.post("/brightness")
def set_brightness(level: int = Query(..., ge=0, le=100)):
    """
    Set display brightness as a percentage (0-100).
    
    Args:
        level: Brightness percentage (0-100)
    
    Returns:
        Success status and current brightness values
    """
    try:
        from app.core.service_container import get_service
        display_service = get_service("display_service")
        
        if not display_service.is_available():
            return {
                "status": "error",
                "message": "Display device not available"
            }
        
        success = display_service.set_brightness_percent(float(level))
        
        if success:
            return {
                "status": "success",
                "message": f"Brightness set to {level}%",
                "brightness": display_service.get_brightness(),
                "brightness_percent": display_service.get_brightness_percent(),
                "max_brightness": display_service.get_max_brightness()
            }
        else:
            return {
                "status": "error",
                "message": f"Failed to set brightness to {level}%"
            }
    except Exception as e:
        logger.error(f"Error setting brightness: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


@router.post("/brightness/increase")
def increase_brightness(step: int = Query(5, ge=1, le=50)):
    """
    Increase display brightness by a step value.
    
    Args:
        step: Amount to increase in percentage points (default 5, max 50)
    
    Returns:
        Success status and current brightness values
    """
    try:
        from app.core.service_container import get_service
        display_service = get_service("display_service")
        
        if not display_service.is_available():
            return {
                "status": "error",
                "message": "Display device not available"
            }
        
        # Convert step from percentage to absolute value
        max_brightness = display_service.get_max_brightness()
        if max_brightness is None:
            return {
                "status": "error",
                "message": "Could not determine max brightness"
            }
        
        step_absolute = int((step / 100) * max_brightness)
        success = display_service.increase_brightness(step_absolute)
        
        if success:
            return {
                "status": "success",
                "message": f"Brightness increased by {step}%",
                "brightness": display_service.get_brightness(),
                "brightness_percent": display_service.get_brightness_percent(),
                "max_brightness": max_brightness
            }
        else:
            return {
                "status": "error",
                "message": "Failed to increase brightness"
            }
    except Exception as e:
        logger.error(f"Error increasing brightness: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


@router.post("/brightness/decrease")
def decrease_brightness(step: int = Query(5, ge=1, le=50)):
    """
    Decrease display brightness by a step value.
    
    Args:
        step: Amount to decrease in percentage points (default 5, max 50)
    
    Returns:
        Success status and current brightness values
    """
    try:
        from app.core.service_container import get_service
        display_service = get_service("display_service")
        
        if not display_service.is_available():
            return {
                "status": "error",
                "message": "Display device not available"
            }
        
        # Convert step from percentage to absolute value
        max_brightness = display_service.get_max_brightness()
        if max_brightness is None:
            return {
                "status": "error",
                "message": "Could not determine max brightness"
            }
        
        step_absolute = int((step / 100) * max_brightness)
        success = display_service.decrease_brightness(step_absolute)
        
        if success:
            return {
                "status": "success",
                "message": f"Brightness decreased by {step}%",
                "brightness": display_service.get_brightness(),
                "brightness_percent": display_service.get_brightness_percent(),
                "max_brightness": max_brightness
            }
        else:
            return {
                "status": "error",
                "message": "Failed to decrease brightness"
            }
    except Exception as e:
        logger.error(f"Error decreasing brightness: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


@router.get("/status")
def get_display_status():
    """Get complete display status."""
    try:
        from app.core.service_container import get_service
        display_service = get_service("display_service")
        
        return {
            "status": "success",
            "display": display_service.get_status()
        }
    except Exception as e:
        logger.error(f"Error getting display status: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
