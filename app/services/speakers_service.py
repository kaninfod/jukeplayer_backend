

import logging
from typing import Dict, List, Optional
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
        context = {}
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
        self._default_name: Optional[str] = None

    def initialize_speakers(self, speakers: List[dict]):
        """Create the speaker registry from the config store's speaker list:
        entries are {name, backend, options, is_default}."""
        from app.services import MediaPlayerService
        from app.playback_backends.factory import get_playback_backend_by_name
        from app.core.service_container import get_service

        for entry in speakers:
            device_name = entry.get("name")
            if not device_name or device_name in self._speakers:
                continue
            backend = get_playback_backend_by_name(
                entry.get("backend", "chromecast"),
                device_name=device_name,
                options=entry.get("options") or {},
            )
            mediaplayer = MediaPlayerService(
                event_bus=get_service("event_bus"),
                playback_backend=backend,
                device_name=device_name
            )
            self._speakers[device_name] = Speaker(str(uuid.uuid4()), device_name, entry.get("backend", "chromecast"), mediaplayer)
            if entry.get("is_default") and not self._default_name:
                self._default_name = device_name
            logger.info(f"[SpeakersService]  Created MediaPlayerService for device: {device_name}")

    def get_speaker(self, speaker_id: str = None, speaker_name: str = None) -> Optional[Speaker]:
        if speaker_name:
            return self._speakers.get(speaker_name)
        if speaker_id:
            for speaker in self._speakers.values():
                if speaker.speaker_id == speaker_id:
                    return speaker
        return None

    def get_default_speaker(self) -> Optional[Speaker]:
        """Return the speaker flagged as default in the config store, or the
        first configured speaker. No env fallback — the store is authoritative."""
        if self._default_name and self._default_name in self._speakers:
            return self._speakers[self._default_name]
        return next(iter(self._speakers.values()), None)
    def get_all_speakers(self) -> Dict[str, Speaker]:
        return self._speakers
    
    def to_dict(self):
        result = {} 
        for speaker in self._speakers.values():
            result[speaker.speaker_name] = speaker.to_dict()
        
        return result
        