import logging
logger = logging.getLogger(__name__)

"""
Configuration management for the jukebox application.
Loads environment variables and provides centralized access to configuration settings.
"""
import os
from dotenv import load_dotenv
from typing import Optional

# Load environment variables from .env file
load_dotenv()

class Config:
    # === RFID BLOCK CONFIGURATION ===
    # Dict mapping logical names to block numbers for RFID
    RFID_BLOCKS = {
        "album_id": 4
    }
    # === NETWORK CONFIGURATION ===
    # Subsonic/Navidrome Configuration
    SUBSONIC_URL: str = os.getenv("SUBSONIC_URL", "http://localhost:4747")
    SUBSONIC_USER: str = os.getenv("SUBSONIC_USER", "")  # Required from .env
    SUBSONIC_PASS: str = os.getenv("SUBSONIC_PASS", "")  # Required from .env
    SUBSONIC_CLIENT: str = os.getenv("SUBSONIC_CLIENT", "jukebox")
    SUBSONIC_API_VERSION: str = os.getenv("SUBSONIC_API_VERSION", "1.15.0")
    # Optional: Basic Auth at reverse proxy (NPM) for Subsonic/Gonic
    SUBSONIC_PROXY_BASIC_USER: str = os.getenv("SUBSONIC_PROXY_BASIC_USER", "")
    SUBSONIC_PROXY_BASIC_PASS: str = os.getenv("SUBSONIC_PROXY_BASIC_PASS", "")
    
    # === TIMEOUT CONFIGURATION ===
    # Chromecast Operation Timeouts (seconds)
    CHROMECAST_DISCOVERY_TIMEOUT: int = int(os.getenv("CHROMECAST_DISCOVERY_TIMEOUT", "3"))  # Time to discover devices on network
    CHROMECAST_WAIT_TIMEOUT: int = int(os.getenv("CHROMECAST_WAIT_TIMEOUT", "10"))           # Time to wait for device to be ready
    
    # Network Request Timeouts (seconds)
    HTTP_REQUEST_TIMEOUT: int = int(os.getenv("HTTP_REQUEST_TIMEOUT", "10"))                 # HTTP requests (album covers, API calls)
    
    # RFID Hardware Timeouts
    RFID_POLL_INTERVAL: float = float(os.getenv("RFID_POLL_INTERVAL", "1.0"))              # Seconds between RFID reads
    RFID_READ_TIMEOUT: float = float(os.getenv("RFID_READ_TIMEOUT", "5.0"))                # Timeout for RFID card read
    RFID_THREAD_JOIN_TIMEOUT: int = int(os.getenv("RFID_THREAD_JOIN_TIMEOUT", "1"))        # Time to wait for RFID thread cleanup
    
    # === DEVICE CONFIGURATION ===
    # Chromecast Device Configuration
    # List of all available Chromecast devices in your home
    CHROMECAST_DEVICES: list = [
        device.strip() for device in os.getenv("CHROMECAST_DEVICES", "Living Room,Bedroom,Kitchen").split(",")
    ]
    # Default Chromecast device to connect to on startup
    DEFAULT_CHROMECAST_DEVICE: str = os.getenv("DEFAULT_CHROMECAST_DEVICE", "Living Room")
    # Fallback devices to try if primary device is offline (in priority order)
    CHROMECAST_FALLBACK_DEVICES: list = [
        device.strip() for device in os.getenv("CHROMECAST_FALLBACK_DEVICES", "Bedroom,Kitchen").split(",")
    ]

    # Playback backend selection: chromecast | mpv
    PLAYBACK_BACKEND: str = os.getenv("PLAYBACK_BACKEND", "chromecast").strip().lower()

    # MPV local player configuration
    MPV_BINARY: str = os.getenv("MPV_BINARY", "mpv")
    MPV_IPC_SOCKET: str = os.getenv("MPV_IPC_SOCKET", "/tmp/jukebox-mpv.sock")
    MPV_AUDIO_DEVICE: str = os.getenv("MPV_AUDIO_DEVICE", "")
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

    # Optional Bluetooth speaker for local playback
    BT_SPEAKER_MAC: str = os.getenv("BT_SPEAKER_MAC", "")
    BT_AUTO_RECONNECT: bool = os.getenv("BT_AUTO_RECONNECT", "true").lower() == "true"
    
    # Display Configuration  
    DISPLAY_WIDTH: int = int(os.getenv("DISPLAY_WIDTH", "480"))
    DISPLAY_HEIGHT: int = int(os.getenv("DISPLAY_HEIGHT", "320"))
    DISPLAY_ROTATION: int = int(os.getenv("DISPLAY_ROTATION", "0"))
    
    # === FONT CONFIGURATION ===
    # Font base directory (relative to project root)
    FONT_BASE_PATH: str = os.getenv("FONT_BASE_PATH", "fonts")
    
    @classmethod
    def get_font_definitions(cls):
        """Get font definitions with relative paths from font base directory"""
        import os
        base_path = cls.FONT_BASE_PATH
        return [
            {"name": "title", "path": os.path.join(base_path, "opensans", "OpenSans-Regular.ttf"), "size": 20},
            {"name": "info", "path": os.path.join(base_path, "opensans", "OpenSans-Regular.ttf"), "size": 18},
            {"name": "small", "path": os.path.join(base_path, "opensans", "OpenSans-Regular.ttf"), "size": 12},
            {"name": "symbols", "path": os.path.join(base_path, "symbolfont", "symbolfont.ttf"), "size": 24},
            {"name": "oswald_semi_bold", "path": os.path.join(base_path, "Oswald-SemiBold.ttf"), "size": 24}
        ]
    
    # Legacy FONT_DEFINITIONS for backward compatibility - will be deprecated
    @property
    def FONT_DEFINITIONS(self):
        return self.get_font_definitions()
    
    # === DATABASE CONFIGURATION ===
    # SQLite database - no additional config needed, uses app/database/album.db

    # === LOGGING CONFIGURATION ===
    LOG_SERVER_HOST: str = os.getenv("LOG_SERVER_HOST", "localhost")
    LOG_SERVER_PORT: int = int(os.getenv("LOG_SERVER_PORT", "514"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    DEBUG_MODE: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"
    # API Docs / OpenAPI exposure (can enable without DEBUG_MODE)
    ENABLE_DOCS: bool = os.getenv("ENABLE_DOCS", "false").lower() == "true"
    DOCS_URL: str = os.getenv("DOCS_URL", "/docs")
    OPENAPI_URL: str = os.getenv("OPENAPI_URL", "/openapi.json")

    # === API SECURITY ===
    # API key used to protect public API endpoints. If unset, only localhost is allowed by default.
    API_KEY: str = os.getenv("API_KEY", "")
    # Web UI Basic Auth credentials (optional fallback authentication method)
    WEB_BASIC_AUTH_USER: str = os.getenv("WEB_BASIC_AUTH_USER", "")
    WEB_BASIC_AUTH_PASS: str = os.getenv("WEB_BASIC_AUTH_PASS", "")
    # Comma-separated list of allowed CORS origins, e.g. "https://example.com,https://www.example.com"
    CORS_ALLOW_ORIGINS: str = os.getenv("CORS_ALLOW_ORIGINS", "*")
    # Comma-separated list of allowed hosts for Host header, e.g. "example.com,www.example.com"
    ALLOWED_HOSTS: str = os.getenv("ALLOWED_HOSTS", "*")
    # Allow 127.0.0.1 to access API without API key (for internal server-side calls)
    ALLOW_LOCAL_API_BYPASS: bool = os.getenv("ALLOW_LOCAL_API_BYPASS", "true").lower() == "true"
    # Toggle automatic HTTP -> HTTPS redirect (use when running behind TLS-terminating reverse proxy)
    ENABLE_HTTPS_REDIRECT: bool = os.getenv("ENABLE_HTTPS_REDIRECT", "false").lower() == "true"

    # === WEB URL CONFIGURATION ===
    # Public base URL where this jukebox is reachable by browsers/Chromecast
    # Example: https://jukeplayer.example.com
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "")

    # === NOTE: GPIO AND HARDWARE CONFIGURATION ===
    # GPIO configuration has been moved to Pi client (Jukeplayer_rpi)
    # Backend no longer manages hardware - only Pi client handles GPIO pins, buttons, displays, etc.
    # This separation allows backend to run on any platform (Mac, Linux, Docker, etc.)

    # === PATH CONFIGURATION ===
    STATIC_FILE_PATH: str = os.getenv("STATIC_FILE_PATH", "static_files")
    
    # Icon definitions for use throughout the app
    ICON_DEFINITIONS = [
        {"name": "contactless", "path": "contactless.png", "width": 80, "height": 80},
        {"name": "library_music", "path": "library_music.png", "width": 80, "height": 80},
        {"name": "add_circle", "path": "add_circle.png", "width": 80, "height": 80},
        {"name": "error", "path": "error.png", "width": 80, "height": 80},
        {"name": "play_circle", "path": "play_circle.png", "width": 80, "height": 80},
        {"name": "pause_circle", "path": "pause_circle.png", "width": 80, "height": 80},
        {"name": "stop_circle", "path": "stop_circle.png", "width": 80, "height": 80},
        {"name": "standby_settings", "path": "power_settings.png", "width": 80, "height": 80},
        {"name": "klangmeister", "path": "klangmeister.png", "width": 480, "height": 320},
    ]


    @classmethod
    def get_image_path(cls, file_name: str) -> str:
        local_path = os.path.join(cls.STATIC_FILE_PATH, file_name)
        return local_path

    @classmethod
    def get_icon_path(cls, icon_name: str) -> str:
        icon_def = next((icon for icon in cls.ICON_DEFINITIONS if icon["name"] == icon_name), None)
        if icon_def:
            return cls.get_image_path(icon_def["path"])
        return False

    @classmethod
    def get_database_url(cls) -> str:
        """Generate the database connection URL - using SQLite"""
        import os
        # Get the absolute path to the database file
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path = os.path.join(base_dir, "app", "database", "album.db")
        return f"sqlite:///{db_path}"
    
    @classmethod
    def validate_config(cls) -> bool:
        """Validate that all required configuration is present"""
        required_vars = [
            "SUBSONIC_USER", 
            "SUBSONIC_PASS"
        ]
        
        missing_vars = []
        for var in required_vars:
            if not getattr(cls, var):
                missing_vars.append(var)
        
        if missing_vars:
            logger.error(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
            return False
        
        # Security warnings (informational)
        if cls.CORS_ALLOW_ORIGINS == "*" and not cls.DEBUG_MODE:
            logger.info("ℹ️  CORS is set to '*' for local access.")

        logger.info("✅ All required configuration variables are present")
        return True

# Create a global config instance
config = Config()
