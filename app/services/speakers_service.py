

import logging
from typing import Dict, Optional
import uuid
    
logger = logging.getLogger(__name__)
class Speaker:
    def __init__(self, speaker_id: str, name: str, backend: str, mediaplayer: object):
        self.speaker_name = name
        self.speaker_id = speaker_id
        self.mediaplayer = mediaplayer
        self.backend = backend
        self.clients = set()

    def to_dict(self):
        if self.mediaplayer:
            context = self.mediaplayer.get_context()
        return {
            "speaker_name": self.speaker_name,
            "speaker_id": self.speaker_id,
            "backend": self.backend,
            "clients": list(self.clients),
            "mediaplayer": {
                "status": context.get("status"),
                "current_track": context.get("current_track"),
                "playlist_count": context.get("playlist_count")
            }
        }


class SpeakersService:
    def __init__(self):
        self._speakers: Dict[str, Speaker] = {}
    
    def initialize_speakers(self, device_config: Dict[str, str]):
        from app.services import MediaPlayerService
        from app.playback_backends.factory import get_playback_backend_by_name
        from app.core.service_container import get_service

        for device_name, backend_type in device_config.items():
            if device_name not in self._speakers:
                backend = get_playback_backend_by_name(backend_type, device_name)
                mediaplayer = MediaPlayerService(
                    event_bus=get_service("event_bus"),
                    playback_backend=backend,
                    device_name=device_name
                )
                self._speakers[device_name] = Speaker(str(uuid.uuid4()), device_name, backend_type, mediaplayer)
                logger.info(f"[SpeakersService]  Created MediaPlayerService for device: {device_name}")


    
    def get_speaker(self, speaker_id: str) -> Optional[Speaker]:
        return self._speakers.get(speaker_id)
    
    def get_all_speakers(self) -> Dict[str, Speaker]:
        return self._speakers
    
    def to_dict(self):
        result = {} 
        for speaker in self._speakers.values():
            result[speaker.speaker_name] = speaker.to_dict()
        
        return result
        