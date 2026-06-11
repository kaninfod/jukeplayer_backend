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
    from app.services.nfc_encoding_state import NfcEncodingStateService
    return NfcEncodingStateService()


def create_config(container):
    from app.config import config
    return config

def create_event_bus(container):
    from app.core.event_bus import event_bus
    return event_bus

def create_album_database(container):
    from app.database.album_db import AlbumDatabase
    config = container.get('config')
    return AlbumDatabase(config)

def create_subsonic_service(container):
    from app.services.subsonic_service import SubsonicService
    config = container.get('config')
    return SubsonicService(config)

# def create_media_player_service(container):
#     """
#     Phase 1: Get default player instance from ClientRegistry.
#     For backward compatibility, returns the first player instance (or default device).
#     """
#     from app.config import config
    
#     # client_registry = container.get('client_registry')
#     # instances = client_registry.list_player_instances()
    
#     if instances:
#         # Return the first instance (for backward compatibility)
#         return instances[0]
#     else:
#         # Fallback: create a default instance if registry is empty
#         logger.warning("No player instances in registry, creating default instance")
#         from app.services import MediaPlayerService
#         from app.playback_backends.factory import get_playback_backend
#         event_bus = container.get('event_bus')
#         return MediaPlayerService(event_bus, playback_backend=get_playback_backend())

def create_playback_service(container):
    from app.services.playback_service import PlaybackService
    return PlaybackService(
        player=None,
        album_db=container.get('album_database'),
        subsonic_service=container.get('subsonic_service'),
        event_bus=container.get('event_bus')
    )

# def create_client_registry(container):
#     from app.services.client_registry import ClientRegistry
#     from app.config import config
    
#     registry = ClientRegistry()
    
#     # Initialize player instances from configured devices
#     # Uses PLAYBACK_DEVICES env var format: device_name=backend_type,device_name=backend_type,...
#     device_config = config.PLAYBACK_DEVICES
    
#     if device_config:
#         registry.initialize_player_instances(device_config)
#         logger.info(f"ClientRegistry initialized with devices: {list(device_config.keys())} and backends: {list(device_config.values())}")
#     else:
#         logger.warning("No devices configured in PLAYBACK_DEVICES")
    
#     return registry

def create_speaker_broker_service(container):
    from app.services.speaker_broker_service import SpeakerBrokerService
    control_clients = container.get('control_clients_service')
    speakers = container.get('speakers_service')
    event_bus = container.get('event_bus')
    return SpeakerBrokerService(control_clients, speakers, event_bus)

def create_control_clients_service(container):
    from app.services.control_clients_service import ControlClientsService

    logger.info("Initializing ControlClientsService")

    control_clients_service = ControlClientsService()
    return control_clients_service

def create_speakers_service(container):
    
    from app.config import config
    from app.services.speakers_service import SpeakersService
    # logger.info("Initializing SpeakersService with device configuration")
    # device_config = config.PLAYBACK_DEVICES

    speakers_service = SpeakersService()
    # if device_config:
    #     speakers_service.initialize_speakers(device_config)
    #     logger.info(f"o-o-o-o-o SpeakersService initialized with devices: {list(device_config.keys())} and backends: {list(device_config.values())}")
    return speakers_service  


# --- Setup function ---
def setup_service_container():
    """Configure all services in the container"""
    global container
    container = ServiceContainer()
    # Register core services as singletons
    container.register_singleton('config', create_config)
    container.register_singleton('nfc_encoding_state', create_nfc_encoding_state)
    container.register_singleton('event_bus', create_event_bus)
    container.register_singleton('album_database', create_album_database)
    container.register_singleton('subsonic_service', create_subsonic_service)
    
    # Register ClientRegistry BEFORE MediaPlayerService (dependency order)
    # container.register_singleton('client_registry', create_client_registry)
    container.register_singleton('control_clients_service', create_control_clients_service)
    container.register_singleton('speakers_service', create_speakers_service)
    container.register_singleton('speaker_broker_service', create_speaker_broker_service)

    # Register media player service as singleton (gets default instance from registry)
    # container.register_singleton('media_player_service', create_media_player_service)
    container.register_singleton('playback_service', create_playback_service)

    # logger.info("Forcing eager initialization of SpeakersService...")
    # _ = container.get('speakers_service')
    # __ = container.get('speaker_broker_service')

    return container

# --- Global access helper ---
container = None
def get_service(name: str):
    """Global service accessor"""
    if container is None:
        raise RuntimeError("Service container not initialized")
    return container.get(name)
