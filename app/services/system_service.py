"""
System control services for the jukebox application.
Provides reusable system operations like reboot and shutdown.
"""
import logging
import time
import os
import subprocess
from typing import Dict, Any

logger = logging.getLogger(__name__)

class SystemService:
    """Service class for system operations like reboot and shutdown."""
    
    def __init__(self):
        # Use platform-agnostic temp directory
        import tempfile
        self.temp_dir = os.path.join(tempfile.gettempdir(), "jukebox")
        self.reboot_trigger_path = f"{self.temp_dir}/reboot_trigger"
        self.shutdown_trigger_path = f"{self.temp_dir}/shutdown_trigger"
        self.restart_trigger_path = f"{self.temp_dir}/restart_trigger"
        
        # Ensure temp directory exists
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Subscribe to system events (service handles its own events)
        self._subscribe_to_system_events()
    
    def _subscribe_to_system_events(self):
        """Subscribe to system events - service handles its own operations."""
        from app.core import event_bus, EventType
        
        # Operation events
        event_bus.subscribe(EventType.SYSTEM_REBOOT_REQUESTED, self._handle_reboot_event)
        event_bus.subscribe(EventType.SYSTEM_SHUTDOWN_REQUESTED, self._handle_shutdown_event)
        event_bus.subscribe(EventType.SYSTEM_RESTART_REQUESTED, self._handle_restart_event)
        
        # Cancellation events
        event_bus.subscribe(EventType.SYSTEM_REBOOT_CANCELLED, self._handle_reboot_cancel_event)
        event_bus.subscribe(EventType.SYSTEM_SHUTDOWN_CANCELLED, self._handle_shutdown_cancel_event)
        event_bus.subscribe(EventType.SYSTEM_RESTART_CANCELLED, self._handle_restart_cancel_event)
        
        logger.info("SystemService: Subscribed to system operation and cancellation events")
    
    def _handle_reboot_event(self, event):
        """Handle SYSTEM_REBOOT_REQUESTED event."""
        reason = event.payload.get("reason", "event_handler")
        source = event.payload.get("source", "unknown")
        
        logger.info(f"SystemService: SYSTEM_REBOOT_REQUESTED event received - reason: {reason}, source: {source}")
        
        result = self.request_reboot(reason=reason)
        
        if result["status"] == "success":
            logger.info(f"SystemService: Reboot trigger file created successfully")
        else:
            logger.error(f"SystemService: Failed to create reboot trigger file: {result['message']}")
        
        return result
    
    def _handle_shutdown_event(self, event):
        """Handle SYSTEM_SHUTDOWN_REQUESTED event."""
        reason = event.payload.get("reason", "event_handler")
        source = event.payload.get("source", "unknown")
        
        logger.info(f"SystemService: SYSTEM_SHUTDOWN_REQUESTED event received - reason: {reason}, source: {source}")
        
        result = self.request_shutdown(reason=reason)
        
        if result["status"] == "success":
            logger.info(f"SystemService: Shutdown trigger file created successfully")
        else:
            logger.error(f"SystemService: Failed to create shutdown trigger file: {result['message']}")
        
        return result
    
    def _handle_restart_event(self, event):
        """Handle SYSTEM_RESTART_REQUESTED event."""
        reason = event.payload.get("reason", "event_handler")
        source = event.payload.get("source", "unknown")
        
        logger.info(f"SystemService: SYSTEM_RESTART_REQUESTED event received - reason: {reason}, source: {source}")
        
        result = self.request_restart(reason=reason)
        
        if result["status"] == "success":
            logger.info(f"SystemService: Restart trigger file created successfully")
        else:
            logger.error(f"SystemService: Failed to create restart trigger file: {result['message']}")
        
        return result
    
    def _handle_reboot_cancel_event(self, event):
        """Handle SYSTEM_REBOOT_CANCELLED event."""
        source = event.payload.get("source", "unknown")
        
        logger.info(f"SystemService: SYSTEM_REBOOT_CANCELLED event received - source: {source}")
        
        result = self.cancel_reboot()
        
        logger.info(f"SystemService: Reboot cancellation result: {result['status']} - {result['message']}")
        
        return result
    
    def _handle_shutdown_cancel_event(self, event):
        """Handle SYSTEM_SHUTDOWN_CANCELLED event."""
        source = event.payload.get("source", "unknown")
        
        logger.info(f"SystemService: SYSTEM_SHUTDOWN_CANCELLED event received - source: {source}")
        
        result = self.cancel_shutdown()
        
        logger.info(f"SystemService: Shutdown cancellation result: {result['status']} - {result['message']}")
        
        return result
    
    def _handle_restart_cancel_event(self, event):
        """Handle SYSTEM_RESTART_CANCELLED event."""
        source = event.payload.get("source", "unknown")
        
        logger.info(f"SystemService: SYSTEM_RESTART_CANCELLED event received - source: {source}")
        
        result = self.cancel_restart()
        
        logger.info(f"SystemService: Restart cancellation result: {result['status']} - {result['message']}")
        
        return result

    def request_reboot(self, reason: str = "api_request") -> Dict[str, Any]:
        """
        Request a system reboot by creating a trigger file for cron to process.
        
        Args:
            reason: Optional reason for the reboot (for logging)
            
        Returns:
            Dict with status and message
        """
        try:
            logger.info(f"System reboot requested - reason: {reason}")
            
            # Create trigger file with timestamp and reason
            trigger_content = f"reboot_requested_at_{time.time()}_reason_{reason}"
            
            with open(self.reboot_trigger_path, "w") as f:
                f.write(trigger_content)
            
            logger.info(f"Reboot trigger file created: {self.reboot_trigger_path}")
            
            return {
                "status": "success",
                "message": "System reboot scheduled (will execute within 1 minute)",
                "trigger_file": self.reboot_trigger_path,
                "reason": reason
            }
            
        except Exception as e:
            logger.error(f"Failed to create reboot trigger file: {e}")
            return {
                "status": "error",
                "message": f"Failed to schedule reboot: {str(e)}",
                "reason": reason
            }
    
    def is_reboot_pending(self) -> bool:
        """
        Check if a reboot is currently pending (trigger file exists).
        
        Returns:
            True if reboot is pending, False otherwise
        """
        return os.path.exists(self.reboot_trigger_path)
    
    def cancel_reboot(self) -> Dict[str, Any]:
        """
        Cancel a pending reboot by removing the trigger file.
        
        Returns:
            Dict with status and message
        """
        try:
            if self.is_reboot_pending():
                os.remove(self.reboot_trigger_path)
                logger.info("Pending reboot cancelled - trigger file removed")
                return {
                    "status": "success",
                    "message": "Pending reboot cancelled"
                }
            else:
                return {
                    "status": "info",
                    "message": "No pending reboot to cancel"
                }
                
        except Exception as e:
            logger.error(f"Failed to cancel reboot: {e}")
            return {
                "status": "error",
                "message": f"Failed to cancel reboot: {str(e)}"
            }
    
    def request_shutdown(self, reason: str = "api_request") -> Dict[str, Any]:
        """
        Request a system shutdown by creating a trigger file for cron to process.
        
        Args:
            reason: Optional reason for the shutdown (for logging)
            
        Returns:
            Dict with status and message
        """
        try:
            logger.info(f"System shutdown requested - reason: {reason}")
            
            # Create trigger file with timestamp and reason
            trigger_content = f"shutdown_requested_at_{time.time()}_reason_{reason}"
            
            with open(self.shutdown_trigger_path, "w") as f:
                f.write(trigger_content)
            
            logger.info(f"Shutdown trigger file created: {self.shutdown_trigger_path}")
            
            return {
                "status": "success",
                "message": "System shutdown scheduled (will execute within 1 minute)",
                "trigger_file": self.shutdown_trigger_path,
                "reason": reason
            }
            
        except Exception as e:
            logger.error(f"Failed to create shutdown trigger file: {e}")
            return {
                "status": "error",
                "message": f"Failed to schedule shutdown: {str(e)}",
                "reason": reason
            }
    
    def is_shutdown_pending(self) -> bool:
        """
        Check if a shutdown is currently pending (trigger file exists).
        
        Returns:
            True if shutdown is pending, False otherwise
        """
        return os.path.exists(self.shutdown_trigger_path)
    
    def cancel_shutdown(self) -> Dict[str, Any]:
        """
        Cancel a pending shutdown by removing the trigger file.
        
        Returns:
            Dict with status and message
        """
        try:
            if self.is_shutdown_pending():
                os.remove(self.shutdown_trigger_path)
                logger.info("Pending shutdown cancelled - trigger file removed")
                return {
                    "status": "success",
                    "message": "Pending shutdown cancelled"
                }
            else:
                return {
                    "status": "info",
                    "message": "No pending shutdown to cancel"
                }
                
        except Exception as e:
            logger.error(f"Failed to cancel shutdown: {e}")
            return {
                "status": "error",
                "message": f"Failed to cancel shutdown: {str(e)}"
            }
    
    def request_restart(self, reason: str = "api_request") -> Dict[str, Any]:
        """
        Request a service restart by creating a trigger file for cron to process.
        Uses the same trigger file approach as reboot/shutdown to bypass systemd restrictions.
        
        Args:
            reason: Optional reason for the restart (for logging)
            
        Returns:
            Dict with status and message
        """
        try:
            logger.info(f"Jukebox service restart requested - reason: {reason}")
            
            # Create trigger file with timestamp and reason
            trigger_content = f"restart_requested_at_{time.time()}_reason_{reason}"
            
            with open(self.restart_trigger_path, "w") as f:
                f.write(trigger_content)
            
            logger.info(f"Restart trigger file created: {self.restart_trigger_path}")
            
            return {
                "status": "success",
                "message": "Jukebox service restart scheduled (will execute within 1 minute)",
                "trigger_file": self.restart_trigger_path,
                "reason": reason
            }
            
        except Exception as e:
            logger.error(f"Failed to create restart trigger file: {e}")
            return {
                "status": "error",
                "message": f"Failed to schedule restart: {str(e)}",
                "reason": reason
            }
    
    def is_restart_pending(self) -> bool:
        """
        Check if a restart is currently pending (trigger file exists).
        
        Returns:
            True if restart is pending, False otherwise
        """
        return os.path.exists(self.restart_trigger_path)
    
    def cancel_restart(self) -> Dict[str, Any]:
        """
        Cancel a pending restart by removing the trigger file.
        
        Returns:
            Dict with status and message
        """
        try:
            if self.is_restart_pending():
                os.remove(self.restart_trigger_path)
                logger.info("Pending restart cancelled - trigger file removed")
                return {
                    "status": "success",
                    "message": "Pending restart cancelled"
                }
            else:
                return {
                    "status": "info",
                    "message": "No pending restart to cancel"
                }
                
        except Exception as e:
            logger.error(f"Failed to cancel restart: {e}")
            return {
                "status": "error",
                "message": f"Failed to cancel restart: {str(e)}"
            }
    
    def get_system_status(self) -> Dict[str, Any]:
        """
        Get current status of all pending system operations.
        
        Returns:
            Dict with status of all system operations
        """
        return {
            "reboot_pending": self.is_reboot_pending(),
            "shutdown_pending": self.is_shutdown_pending(),
            "restart_pending": self.is_restart_pending(),
            "service_status": "running"  # Since we're executing this, service is running
        }
    


# Global instance for easy importing
system_service = SystemService()