

import logging
from typing import Dict, List, Optional
import uuid

logger = logging.getLogger(__name__)
class Speaker:
    def __init__(self, speaker_id: str, name: str, backend: str, mediaplayer: object,
                 display_name: str = "", speaker_type: str = "local"):
        self.speaker_name = name
        self.speaker_id = speaker_id
        self.mediaplayer = mediaplayer
        self.backend = backend
        self.display_name = str(display_name or "").strip()
        # runtime state flags (updated by SpeakerManagerService.update_speaker_states)
        self.type = speaker_type            # chromecast | bluetooth | local
        self.available = False              # reachable: on the network / known to bluez
        self.connected = False              # active audio link
        self.bt_mac = None                  # MAC for bluetooth-backed speakers
        self.battery = None                 # battery % (bluetooth, when clearly reported)
        self.clients = set()

    def to_dict(self):
        context = {}
        if self.mediaplayer:
            context = self.mediaplayer.get_context()

        return {
            "speaker_name": self.speaker_name,
            "display_name": self.display_name,
            "speaker_id": self.speaker_id,
            "backend": self.backend,
            "type": self.type,
            "available": self.available,
            "connected": self.connected,
            "bt_mac": self.bt_mac,
            "battery": self.battery,
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
        for entry in speakers:
            device_name = entry.get("name")
            if not device_name or device_name in self._speakers:
                continue
            self._speakers[device_name] = self._build_speaker(entry)
            if entry.get("is_default") and not self._default_name:
                self._default_name = device_name

    def _build_speaker(self, entry: dict) -> Speaker:
        """Construct the backend + MediaPlayerService for one store entry."""
        from app.services import MediaPlayerService
        from app.playback_backends.factory import get_playback_backend_by_name
        from app.core.service_container import get_service

        device_name = entry.get("name")
        backend_name = entry.get("backend", "chromecast")
        backend = get_playback_backend_by_name(
            backend_name,
            device_name=device_name,
            options=entry.get("options") or {},
        )
        mediaplayer = MediaPlayerService(
            event_bus=get_service("event_bus"),
            playback_backend=backend,
            device_name=device_name
        )
        # type from backend + options: BT speakers are mpv-backed with a bluez sink
        from app.services.bluetooth_service import mac_from_sink_id
        audio_device = (entry.get("options") or {}).get("audio_device") or ""
        bt_mac = mac_from_sink_id(audio_device)
        if backend_name == "chromecast":
            speaker_type = "chromecast"
        elif bt_mac:
            speaker_type = "bluetooth"
        else:
            speaker_type = "local"
        logger.info(f"[SpeakersService]  Created MediaPlayerService for device: {device_name}")
        speaker = Speaker(str(uuid.uuid4()), device_name, backend_name, mediaplayer,
                          display_name=str(entry.get("display_name") or ""),
                          speaker_type=speaker_type)
        speaker.bt_mac = bt_mac
        return speaker

    def add_speaker(self, entry: dict) -> Speaker:
        """Live speaker add (Phase B): construct and register without a restart.
        Raises ValueError on empty or already-active names."""
        name = str(entry.get("name") or "").strip().lower()
        if not name:
            raise ValueError("Speaker name is required")
        if name in self._speakers:
            raise ValueError(f"Speaker '{name}' is already active")
        speaker = self._build_speaker({**entry, "name": name})
        self._speakers[name] = speaker
        if entry.get("is_default"):
            self._default_name = name
        return speaker

    def remove_speaker(self, name: str) -> Optional[Speaker]:
        """Live speaker removal: drop it from the registry and return the
        removed object (caller stops playback, disconnects, re-homes clients)."""
        speaker = self._speakers.pop(str(name or "").strip().lower(), None)
        if speaker and self._default_name == speaker.speaker_name:
            self._default_name = None
        return speaker

    def set_default_name(self, name: Optional[str]) -> bool:
        """Point the registry's default at a configured speaker (or clear it;
        get_default_speaker then falls back to the first entry)."""
        if name and name not in self._speakers:
            raise ValueError(f"Unknown speaker: {name}")
        self._default_name = name
        return True

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
        