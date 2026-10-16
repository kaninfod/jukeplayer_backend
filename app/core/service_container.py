# Service Container for Jukebox Application

import logging

logger = logging.getLogger(__name__)


class ServiceContainer:
    """
    Service container for managing dependencies and their lifecycle
    """
    def __init__(self):
        self._services = {}
        self._singletons = {}
    
    def register_singleton(self, name: str, factory_func):
        self._services[name] = factory_func
        self._singletons[name] = True
    
    def register_transient(self, name: str, factory_func):
        self._services[name] = factory_func
        self._singletons[name] = False
    
    def get(self, name: str):
        if name not in self._services:
            raise ValueError(f"Service '{name}' not registered")
        if self._singletons[name]:
            cache_key = f"_instance_{name}"
            if not hasattr(self, cache_key):
                setattr(self, cache_key, self._services[name](self))
            return getattr(self, cache_key)
        else:
            return self._services[name](self)


# --- Service factory functions ---
def create_nfc_encoding_state(container):
    from app.nfc.state import NfcEncodingStateService
    return NfcEncodingStateService()


def create_config(container):
    from app.config import config
    return config

def create_event_bus(container):
    from app.core.event_bus import event_bus
    return event_bus

def create_config_store(container):
    from app.config.store import ConfigStoreService
    from app.config import config
    return ConfigStoreService(path=getattr(config, "CONFIG_FILE", None))

def create_config_service(container):
    from app.config.store import ConfigService
    return ConfigService(store=container.get('config_store'), system_config=container.get('config'))

def create_music_source_registry(container):
    """The music-source registry (the seam, app/music_sources) — now
    CONFIG-DRIVEN from the store's `sources` section:
    - subsonic: on unless explicitly disabled (the creds = the legacy section);
    - ytmusic: registered when enabled AND the device-flow handed over a
      token (persisted inside the section); a broken token skips quietly."""
    from app.music_sources.registry import SourceRegistry
    from app.music_sources.subsonic import SubsonicSource
    from app.config.store import SubsonicConfigAdapter
    config_service = container.get('config_service')
    store = container.get('config_store')
    registry = SourceRegistry(default_pid="subsonic")
    sources_cfg = store.section("sources") or {}
    if (sources_cfg.get("subsonic") or {}).get("enabled", True) is not False:
        registry.register(SubsonicSource(SubsonicConfigAdapter(config_service)))
    ytm = sources_cfg.get("ytmusic") or {}
    if ytm.get("enabled") and ytm.get("token"):
        from app.music_sources.ytmusic import YTMusicSource
        try:
            registry.register(YTMusicSource(ytm))
            logger.info("[sources] ytmusic provider registered")
        except Exception as e:
            logger.warning(f"[sources] ytmusic skipped: {e}")
    else:
        logger.debug("[sources] ytmusic not configured (no token) — skipped")
    return registry


def create_album_store(container):
    """The collection ledger (the record store) — a tiny sqlite beside the
    config store."""
    from app.music_sources.collection import AlbumStore
    import os
    config_path = container.get('config_store').path or os.path.join("data", "config.json")
    return AlbumStore(path=os.path.join(os.path.dirname(config_path) or ".", "collection.db"))

def create_subsonic_service(container):
    """Compat alias: the subsonic SOURCE under its historical container key —
    the /api/subsonic routes, CoverService and the metadata warm-up keep
    consuming the same instance untouched."""
    return container.get('music_sources').get('subsonic')

def create_artist_metadata_service(container):
    from app.music_sources.subsonic.metadata import ArtistMetadataService
    return ArtistMetadataService(container.get('subsonic_service'))

def create_cover_service(container):
    from app.music_sources.covers import CoverService
    return CoverService(container.get('subsonic_service'))

def create_playback_service(container):
    from app.playback.playback_service import PlaybackService
    return PlaybackService(
        music_sources=container.get('music_sources'),
        event_bus=container.get('event_bus')
    )

def create_speaker_broker_service(container):
    from app.speakers.speaker_broker_service import SpeakerBrokerService
    control_clients = container.get('control_clients_service')
    speakers = container.get('speakers_service')
    event_bus = container.get('event_bus')
    return SpeakerBrokerService(control_clients, speakers, event_bus)

def create_control_clients_service(container):
    from app.speakers.control_clients import ControlClientsService

    logger.info("Initializing ControlClientsService")

    control_clients_service = ControlClientsService()
    return control_clients_service

def create_speakers_service(container):
    from app.speakers.speakers_service import SpeakersService
    return SpeakersService()

def create_speaker_manager_service(container):
    from app.speakers.speaker_manager_service import SpeakerManagerService
    return SpeakerManagerService(
        store=container.get('config_store'),
        config_service=container.get('config_service'),
        speakers_service=container.get('speakers_service'),
        broker=container.get('speaker_broker_service'),
        bluetooth_service=container.get('bluetooth_service'),
    )

def create_bluetooth_service(container):
    from app.bluetooth.service import BluetoothService
    return BluetoothService()


# --- Setup function ---
def setup_service_container():
    """Configure all services in the container"""
    global container
    container = ServiceContainer()
    # Register core services as singletons
    container.register_singleton('config', create_config)
    container.register_singleton('nfc_encoding_state', create_nfc_encoding_state)
    container.register_singleton('event_bus', create_event_bus)
    container.register_singleton('config_store', create_config_store)
    container.register_singleton('config_service', create_config_service)
    container.register_singleton('subsonic_service', create_subsonic_service)
    container.register_singleton('music_sources', create_music_source_registry)
    container.register_singleton('album_store', create_album_store)
    container.register_singleton('artist_metadata_service', create_artist_metadata_service)
    container.register_singleton('cover_service', create_cover_service)

    container.register_singleton('control_clients_service', create_control_clients_service)
    container.register_singleton('speakers_service', create_speakers_service)
    container.register_singleton('speaker_broker_service', create_speaker_broker_service)
    container.register_singleton('speaker_manager', create_speaker_manager_service)
    container.register_singleton('bluetooth_service', create_bluetooth_service)

    container.register_singleton('playback_service', create_playback_service)

    return container

# --- Global access helper ---
container = None
def get_service(name: str):
    """Global service accessor"""
    if container is None:
        raise RuntimeError("Service container not initialized")
    return container.get(name)
