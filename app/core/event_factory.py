from enum import Enum
from app.core.event_bus import Event

class EventType(Enum):
    SYSTEM_REBOOT_REQUESTED = "system_reboot_requested"
    SYSTEM_SHUTDOWN_REQUESTED = "system_shutdown_requested"
    SYSTEM_RESTART_REQUESTED = "system_restart_requested"
    SYSTEM_REBOOT_CANCELLED = "system_reboot_cancelled"
    SYSTEM_SHUTDOWN_CANCELLED = "system_shutdown_cancelled"
    SYSTEM_RESTART_CANCELLED = "system_restart_cancelled"

    TRACK_CHANGED = "track_changed"
    VOLUME_CHANGED = "volume_changed"
    BRIGHTNESS_CHANGED = "brightness_changed"
    TRACK_FINISHED = "track_finished"
    NEXT_TRACK = "next_track"
    PREVIOUS_TRACK = "previous_track"
    PLAY_TRACK = "play_track"
    PLAY_PAUSE = "play_pause"
    STOP = "stop"
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    SET_VOLUME = "set_volume"
    VOLUME_MUTE = "volume_mute"
    
    CLEAR_ERROR = "clear_error"
    BUTTON_PRESSED = "button_pressed"
    ROTARY_ENCODER = "rotary_encoder"
    RFID_READ = "rfid_read"
    SHOW_IDLE = "show_idle"
    SHOW_HOME = "show_home"
    SHOW_MESSAGE = "show_message"
    # Chromecast events
    SHOW_SCREEN_QUEUED = "show_screen_queued"
    ENCODE_CARD = "encode_card"
    NOTIFICATION = "notification"
    TOGGLE_REPEAT_ALBUM = "toggle_repeat_album"

class EventFactory:
    @staticmethod
    def show_screen_queued(screen_type, context, duration=3.0):
        """Create a queued screen event"""
        return Event(
            type=EventType.SHOW_SCREEN_QUEUED,
            payload={
                "screen_type": screen_type,
                "context": context,
                "duration": duration
            }
        )
    @staticmethod
    def notification(payload):
        return Event(
            type=EventType.NOTIFICATION,
            payload=payload
        )
