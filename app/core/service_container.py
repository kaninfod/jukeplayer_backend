# Service Container for Jukebox Application

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

def create_media_player_service(container):
    from app.services import MediaPlayerService
    from app.playback_backends.factory import get_playback_backend
    event_bus = container.get('event_bus')
    return MediaPlayerService(event_bus, playback_backend=get_playback_backend())

def create_playback_service(container):
    from app.services.playback_service import PlaybackService
    return PlaybackService(
        screen_manager=None,
        player=container.get('media_player_service'),
        album_db=container.get('album_database'),
        subsonic_service=container.get('subsonic_service'),
        event_bus=container.get('event_bus')
    )

def create_client_registry(container):
    from app.services.client_registry import ClientRegistry
    return ClientRegistry()

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
    # Register media player service as singleton
    container.register_singleton('media_player_service', create_media_player_service)
    container.register_singleton('playback_service', create_playback_service)

    container.register_singleton('client_registry', create_client_registry)
    return container

# --- Global access helper ---
container = None
def get_service(name: str):
    """Global service accessor"""
    if container is None:
        raise RuntimeError("Service container not initialized")
    return container.get(name)
