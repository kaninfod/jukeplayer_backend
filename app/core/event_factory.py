from enum import Enum

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

    RFID_READ = "rfid_read"
    TOGGLE_REPEAT = "toggle_repeat"

    REGISTER_CONTROL_CLIENT = "register_control_client"
    UNREGISTER_CONTROL_CLIENT = "unregister_control_client"
    ASSIGN_SPEAKER = "assign_speaker"
