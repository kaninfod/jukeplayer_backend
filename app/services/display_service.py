"""
Display service for managing screen brightness and display properties.
Wraps the DisplayDevice hardware controller with error handling and events.
"""

import logging
from typing import Optional
from app.hardware.devices.display import DisplayDevice
from app.core import Event, EventType

logger = logging.getLogger(__name__)


class DisplayService:
    """
    Service for display/screen control (brightness, etc).
    Provides a higher-level interface to the DisplayDevice hardware controller.
    """
    
    def __init__(self, event_bus=None):
        """
        Initialize DisplayService.
        
        Args:
            event_bus: EventBus instance for emitting display events
        """
        self.device = DisplayDevice()
        self.event_bus = event_bus
        
        if self.device.is_available():
            logger.info("DisplayService initialized successfully")
            logger.info(f"Display device available at {self.device.backlight_path}")
        else:
            logger.warning("DisplayService initialized but display device not available")
    
    def is_available(self) -> bool:
        """Check if display device is available."""
        return self.device.is_available()
    
    def get_brightness(self) -> Optional[int]:
        """Get current brightness (absolute value 0-31)."""
        return self.device.get_brightness()
    
    def get_brightness_percent(self) -> Optional[float]:
        """Get current brightness as percentage (0-100)."""
        return self.device.get_brightness_percent()
    
    def get_max_brightness(self) -> Optional[int]:
        """Get maximum brightness value."""
        return self.device.get_max_brightness()
    
    def set_brightness(self, brightness: int) -> bool:
        """
        Set brightness to an absolute value (0-31).
        Emits BRIGHTNESS_CHANGED event on success.
        
        Args:
            brightness: Brightness level (0 to max_brightness)
        
        Returns:
            True if successful, False otherwise
        """
        if not self.device.is_available():
            logger.error("Display device not available")
            return False
        
        success = self.device.set_brightness(brightness)
        
        if success and self.event_bus:
            try:
                current_percent = self.device.get_brightness_percent()
                self.event_bus.emit(Event(
                    type=EventType.BRIGHTNESS_CHANGED,
                    payload={
                        "brightness": brightness,
                        "brightness_percent": current_percent,
                        "max_brightness": self.device.get_max_brightness()
                    }
                ))
            except Exception as e:
                logger.error(f"Error emitting BRIGHTNESS_CHANGED event: {e}")
        
        return success
    
    def set_brightness_percent(self, percent: float) -> bool:
        """
        Set brightness as a percentage (0-100).
        Emits BRIGHTNESS_CHANGED event on success.
        
        Args:
            percent: Brightness percentage (0-100)
        
        Returns:
            True if successful, False otherwise
        """
        if not self.device.is_available():
            logger.error("Display device not available")
            return False
        
        success = self.device.set_brightness_percent(percent)
        
        if success and self.event_bus:
            try:
                brightness = self.device.get_brightness()
                self.event_bus.emit(Event(
                    type=EventType.BRIGHTNESS_CHANGED,
                    payload={
                        "brightness": brightness,
                        "brightness_percent": percent,
                        "max_brightness": self.device.get_max_brightness()
                    }
                ))
            except Exception as e:
                logger.error(f"Error emitting BRIGHTNESS_CHANGED event: {e}")
        
        return success
    
    def increase_brightness(self, step: int = 1) -> bool:
        """
        Increase brightness by a step value.
        
        Args:
            step: Amount to increase (default 1)
        
        Returns:
            True if successful, False otherwise
        """
        current = self.device.get_brightness()
        if current is None:
            return False
        
        return self.set_brightness(current + step)
    
    def decrease_brightness(self, step: int = 1) -> bool:
        """
        Decrease brightness by a step value.
        
        Args:
            step: Amount to decrease (default 1)
        
        Returns:
            True if successful, False otherwise
        """
        current = self.device.get_brightness()
        if current is None:
            return False
        
        return self.set_brightness(current - step)
    
    def get_status(self) -> dict:
        """Get complete display status."""
        return {
            "available": self.is_available(),
            "brightness": self.get_brightness(),
            "brightness_percent": self.get_brightness_percent(),
            "max_brightness": self.get_max_brightness(),
            "backlight_path": self.device.backlight_path
        }
