"""
Configuration management for the jukebox backend.
Loads environment variables and provides centralized access to configuration settings.
"""
import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()


def _parse_playback_devices() -> dict:
    """Parse the PLAYBACK_DEVICES env var into a {device_name: backend_type} dict."""
    devices_str = os.getenv("PLAYBACK_DEVICES", "")
    device_config = {}

    if not devices_str:
        logger.warning("PLAYBACK_DEVICES not configured, using empty device config")
        return device_config

    for pair in devices_str.split(','):
        pair = pair.strip()
        if '=' not in pair:
            logger.warning(f"Invalid PLAYBACK_DEVICES format: '{pair}' (expected 'device_name=backend_type')")
            continue
        device_name, backend_type = pair.split('=', 1)
        device_config[device_name.strip().lower()] = backend_type.strip().lower()

    return device_config


class Config:
    # === SUBSONIC / NAVIDROME CONFIGURATION ===
    SUBSONIC_URL: str = os.getenv("SUBSONIC_URL", "http://localhost:4747")
    SUBSONIC_USER: str = os.getenv("SUBSONIC_USER", "")  # Required from .env
    SUBSONIC_PASS: str = os.getenv("SUBSONIC_PASS", "")  # Required from .env
    SUBSONIC_CLIENT: str = os.getenv("SUBSONIC_CLIENT", "jukebox")
    SUBSONIC_API_VERSION: str = os.getenv("SUBSONIC_API_VERSION", "1.15.0")
    # Optional: Basic Auth at reverse proxy (NPM) for Subsonic/Gonic
    SUBSONIC_PROXY_BASIC_USER: str = os.getenv("SUBSONIC_PROXY_BASIC_USER", "")
    SUBSONIC_PROXY_BASIC_PASS: str = os.getenv("SUBSONIC_PROXY_BASIC_PASS", "")

    # === TIMEOUTS ===
    # Chromecast operation timeouts (seconds)
    CHROMECAST_DISCOVERY_TIMEOUT: int = int(os.getenv("CHROMECAST_DISCOVERY_TIMEOUT", "3"))
    CHROMECAST_WAIT_TIMEOUT: int = int(os.getenv("CHROMECAST_WAIT_TIMEOUT", "10"))
    # Network request timeouts (seconds)
    HTTP_REQUEST_TIMEOUT: int = int(os.getenv("HTTP_REQUEST_TIMEOUT", "10"))

    # === DEVICE CONFIGURATION ===
    CHROMECAST_DEVICES: list = [
        device.strip() for device in os.getenv("CHROMECAST_DEVICES", "Living Room,Bedroom,Kitchen").split(",")
    ]
    DEFAULT_CHROMECAST_DEVICE: str = os.getenv("DEFAULT_CHROMECAST_DEVICE", "Living Room")
    CHROMECAST_FALLBACK_DEVICES: list = [
        device.strip() for device in os.getenv("CHROMECAST_FALLBACK_DEVICES", "Bedroom,Kitchen").split(",")
    ]
    # Playback backend fallback for unconfigured speakers: chromecast | mpv
    PLAYBACK_BACKEND: str = os.getenv("PLAYBACK_BACKEND", "chromecast").strip().lower()
    # Unified multi-device configuration: "device_name=backend_type,..." (names lowercase)
    PLAYBACK_DEVICES: dict = _parse_playback_devices()

    # === MPV (LOCAL SPEAKER) CONFIGURATION ===
    MPV_BINARY: str = os.getenv("MPV_BINARY", "mpv")
    MPV_IPC_SOCKET: str = os.getenv("MPV_IPC_SOCKET", "/tmp/jukebox-mpv.sock")
    MPV_EXTRA_ARGS: str = os.getenv("MPV_EXTRA_ARGS", "")
    MPV_STARTUP_TIMEOUT_SECONDS: int = int(os.getenv("MPV_STARTUP_TIMEOUT_SECONDS", "5"))
    MPV_MSG_LEVEL: str = os.getenv("MPV_MSG_LEVEL", "")
    MPV_LOG_FILE: str = os.getenv("MPV_LOG_FILE", "")
    # Friendly name for MPV/Bluetooth device (for UI)
    MPV_DEVICE_NAME: str = os.getenv("MPV_DEVICE_NAME", "MPV Device")
    MPV_CACHE_ENABLED: bool = os.getenv("MPV_CACHE_ENABLED", "true").lower() == "true"
    MPV_CACHE_SECS: int = int(os.getenv("MPV_CACHE_SECS", "90"))
    MPV_DEMUXER_MAX_BYTES: str = os.getenv("MPV_DEMUXER_MAX_BYTES", "128MiB")
    MPV_DEMUXER_MAX_BACK_BYTES: str = os.getenv("MPV_DEMUXER_MAX_BACK_BYTES", "32MiB")
    MPV_AUDIO_BUFFER_SECONDS: float = float(os.getenv("MPV_AUDIO_BUFFER_SECONDS", "1.2"))
    MPV_DIAGNOSTIC_INTERVAL_SECONDS: int = int(os.getenv("MPV_DIAGNOSTIC_INTERVAL_SECONDS", "20"))
    MPV_STALL_WARNING_SECONDS: int = int(os.getenv("MPV_STALL_WARNING_SECONDS", "90"))

    # === LOGGING / SERVER BEHAVIOR ===
    LOG_SERVER_HOST: str = os.getenv("LOG_SERVER_HOST", "localhost")
    _log_port_raw = os.getenv("LOG_SERVER_PORT", "514").split("#")[0].strip()
    LOG_SERVER_PORT: int = int(_log_port_raw) if _log_port_raw.isdigit() else 514
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    DEBUG_MODE: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"
    # API Docs / OpenAPI exposure (can enable without DEBUG_MODE)
    ENABLE_DOCS: bool = os.getenv("ENABLE_DOCS", "false").lower() == "true"
    DOCS_URL: str = os.getenv("DOCS_URL", "/docs")
    OPENAPI_URL: str = os.getenv("OPENAPI_URL", "/openapi.json")

    # === NETWORK / SECURITY ===
    # Comma-separated list of allowed CORS origins, e.g. "https://example.com"
    CORS_ALLOW_ORIGINS: str = os.getenv("CORS_ALLOW_ORIGINS", "*")
    # Toggle automatic HTTP -> HTTPS redirect (use behind a TLS-terminating proxy)
    ENABLE_HTTPS_REDIRECT: bool = os.getenv("ENABLE_HTTPS_REDIRECT", "false").lower() == "true"

    # === WEB URL CONFIGURATION ===
    # Public base URL where this jukebox is reachable by browsers/Chromecast
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "")

    # === PATH CONFIGURATION ===
    STATIC_FILE_PATH: str = os.getenv("STATIC_FILE_PATH", "static_files")

    @classmethod
    def validate_config(cls) -> bool:
        """Validate that all required configuration is present"""
        required_vars = [
            "SUBSONIC_USER",
            "SUBSONIC_PASS"
        ]

        missing_vars = [var for var in required_vars if not getattr(cls, var)]
        if missing_vars:
            logger.error(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
            return False

        if cls.CORS_ALLOW_ORIGINS == "*" and not cls.DEBUG_MODE:
            logger.info("ℹ️  CORS is set to '*' for local access.")

        logger.info("✅ All required configuration variables are present")
        return True


# Create a global config instance
config = Config()