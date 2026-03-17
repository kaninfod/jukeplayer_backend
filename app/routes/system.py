"""
System control routes for the jukebox.
Provides shutdown and reboot functionality.
"""
from fastapi import APIRouter, HTTPException
import logging
import subprocess
import asyncio
import time
import os
from typing import Dict, Any
from app.config import config
from app.core import EventType, Event, event_bus
logger = logging.getLogger(__name__)

# --- Clean event-driven system operations ---
# Note: Event handlers are now in SystemService, not in routes
# The service listens for events and handles the operations


router = APIRouter(prefix="/api/system", tags=["system"])

@router.get("/operations/status")
async def system_operations_status() -> Dict[str, Any]:
    """
    Get comprehensive system status including operations, uptime, and health info.
    Combines system operations status with general system information.
    """
    from app.services import system_service
    import platform
    
    # Try to import psutil, fall back gracefully if not available
    try:
        import psutil
        PSUTIL_AVAILABLE = True
    except ImportError:
        PSUTIL_AVAILABLE = False
    
    try:
        # Get system operations status
        operations_status = system_service.get_system_status()
        
        # Get basic system info
        uptime_result = subprocess.run(
            ["uptime", "-p"], 
            capture_output=True, 
            text=True, 
            timeout=5
        )
        
        hostname_result = subprocess.run(
            ["hostname"], 
            capture_output=True, 
            text=True, 
            timeout=5
        )
        
        # Get load average
        load_result = subprocess.run(
            ["uptime"], 
            capture_output=True, 
            text=True, 
            timeout=5
        )
        
        # Extract load from uptime output (e.g., "load average: 0.52, 0.58, 0.59")
        load_average = "unknown"
        if load_result.returncode == 0 and "load average:" in load_result.stdout:
            load_part = load_result.stdout.split("load average:")[1].strip()
            load_average = load_part
        
        # Get memory and disk info (if psutil is available)
        if PSUTIL_AVAILABLE:
            try:
                memory = psutil.virtual_memory()
                memory_info = {
                    "total_gb": round(memory.total / (1024**3), 2),
                    "available_gb": round(memory.available / (1024**3), 2),
                    "used_percent": memory.percent
                }
            except Exception:
                memory_info = {"error": "Unable to get memory info"}
            
            try:
                disk = psutil.disk_usage('/home/pi/shared/jukebox')
                disk_info = {
                    "total_gb": round(disk.total / (1024**3), 2),
                    "free_gb": round(disk.free / (1024**3), 2),
                    "used_percent": round((disk.used / disk.total) * 100, 1)
                }
            except Exception:
                disk_info = {"error": "Unable to get disk info"}
        else:
            memory_info = {"info": "psutil not available"}
            disk_info = {"info": "psutil not available"}
        
        # Get Python/service info
        python_version = platform.python_version()
        
        # Get jukebox-specific status
        try:
            # Check if essential directories exist
            essential_dirs = {
                "tmp_dir": "/home/pi/shared/jukebox/tmp",
                "scripts_dir": "/home/pi/shared/jukebox/scripts",
                "static_files": "/home/pi/shared/jukebox/static_files"
            }
            
            dir_status = {}
            for name, path in essential_dirs.items():
                dir_status[name] = {
                    "exists": os.path.exists(path),
                    "writable": os.access(path, os.W_OK) if os.path.exists(path) else False
                }
        except Exception:
            dir_status = {"error": "Unable to check directories"}
        
        # Get process info
        try:
            import os as os_module
            current_pid = os_module.getpid()
            process_info = {
                "pid": current_pid,
                "user": os_module.getenv("USER", "unknown")
            }
        except Exception:
            process_info = {"error": "Unable to get process info"}
        
        # Combine all information
        comprehensive_status = {
            # System operations (from SystemService)
            **operations_status,
            
            # Basic system info
            "system_status": "online",
            "hostname": hostname_result.stdout.strip() if hostname_result.returncode == 0 else "unknown",
            "uptime": uptime_result.stdout.strip() if uptime_result.returncode == 0 else "unknown",
            "load_average": load_average,
            
            # Resource info
            "memory": memory_info,
            "disk": disk_info,
            
            # Service info  
            "python_version": python_version,
            "platform": platform.system(),
            "process": process_info,
            
            # Jukebox-specific
            "directories": dir_status,
            "psutil_available": PSUTIL_AVAILABLE,
            
            # Timestamps
            "timestamp": time.time(),
            "timestamp_readable": time.strftime("%Y-%m-%d %H:%M:%S %Z")
        }
        
        return comprehensive_status
        
    except Exception as e:
        logger.error(f"Failed to get comprehensive system status: {e}")
        # Fallback to basic operations status
        return {
            **system_service.get_system_status(),
            "system_status": "error",
            "error": f"Failed to get full system status: {str(e)}",
            "timestamp": time.time()
        }
    
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

