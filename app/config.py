"""System-level configuration for the jukebox backend.

Only bootstrap/system keys live here (read from environment). Everything the
user manages from the web UI — Subsonic, speakers, MPV, logging level, server
behaviour — lives in the JSON config store (app/services/config_store.py).
"""

import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()


class Config:
    # === SYSTEM / BOOTSTRAP (env-only; everything else lives in the store) ===
    # Syslog server for centralized logging
    LOG_SERVER_HOST: str = os.getenv("LOG_SERVER_HOST", "localhost")
    _log_port_raw = os.getenv("LOG_SERVER_PORT", "514").split("#")[0].strip()
    LOG_SERVER_PORT: int = int(_log_port_raw) if _log_port_raw.isdigit() else 514
    # Paths (deployment-level)
    CONFIG_FILE: str = os.getenv("CONFIG_FILE", "data/config.json")
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/jukebox.log")
    # Static covers/assets directory
    STATIC_FILE_PATH: str = os.getenv("STATIC_FILE_PATH", "static_files")
    # Server behaviour toggles (docs exposure; debug tracing)
    ENABLE_DOCS: bool = os.getenv("ENABLE_DOCS", "false").lower() == "true"
    DOCS_URL: str = os.getenv("DOCS_URL", "/docs")
    OPENAPI_URL: str = os.getenv("OPENAPI_URL", "/openapi.json")
    DEBUG_MODE: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"
    # Boot-time log level (the config UI can change it live afterwards)
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


# Create a global config instance
config = Config()