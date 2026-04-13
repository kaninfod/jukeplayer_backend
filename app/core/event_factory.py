from enum import Enum
from app.core.event_bus import Event

class EventType(Enum):


    TRACK_CHANGED = "track_changed"
    TRACK_FINISHED = "track_finished"
    VOLUME_CHANGED = "volume_changed"
    
    NEXT_TRACK = "next_track"
    PREVIOUS_TRACK = "previous_track"
    PLAY_TRACK = "play_track"
    PLAY_ALBUM = "play_album"
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
    TOGGLE_REPEAT = "toggle_repeat"
    TOGGLE_REPEAT_CHANGED = "toggle_repeat_changed"

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
