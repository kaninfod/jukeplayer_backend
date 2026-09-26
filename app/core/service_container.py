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

def create_config_store(container):
    from app.services.config_store import ConfigStoreService
    from app.config import config
    return ConfigStoreService(path=getattr(config, "CONFIG_FILE", None))

def create_config_service(container):
    from app.services.config_store import ConfigService
    return ConfigService(store=container.get('config_store'), system_config=container.get('config'))

def create_subsonic_service(container):
    from app.services.subsonic_service import SubsonicService
    from app.services.config_store import SubsonicConfigAdapter
    config_service = container.get('config_service')
    return SubsonicService(SubsonicConfigAdapter(config_service))

def create_playback_service(container):
    from app.services.playback_service import PlaybackService
    return PlaybackService(
        subsonic_service=container.get('subsonic_service'),
        event_bus=container.get('event_bus')
    )

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
    from app.services.speakers_service import SpeakersService
    return SpeakersService()

def create_speaker_manager_service(container):
    from app.services.speaker_manager_service import SpeakerManagerService
    return SpeakerManagerService(
        store=container.get('config_store'),
        config_service=container.get('config_service'),
        speakers_service=container.get('speakers_service'),
        broker=container.get('speaker_broker_service'),
        bluetooth_service=container.get('bluetooth_service'),
    )

def create_bluetooth_service(container):
    from app.services.bluetooth_service import BluetoothService
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
