"""Operational configuration store (JSON on disk) + merged effective-config view.

Three layers, per the design agreed 2026-09-24:
  1. System env keys (app/config.py)  — secrets-free bootstrap: logging host,
     docs toggle, file paths. Read at boot.
  2. Config store (this file)         — everything managed from the web UI
     (Subsonic, speakers, MPV, logging level, server behaviour). Lives at
     CONFIG_FILE (default data/config.json); atomic writes; 0600 perms.
  3. Effective config (ConfigService) — merged view used by the app, with
     per-key source attribution for the UI.
"""

import json
import logging
import os
import tempfile
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

SECTION_DEFAULTS: Dict[str, Any] = {
    "subsonic": {
        "url": "",
        "user": "",
        "password": "",
        "client": "JukeboxPi",
        "api_version": "1.16.1",
    },
    # list of {"name", "backend": chromecast|mpv, "options": {}, "is_default": bool}
    "speakers": [],
    "mpv": {
        "binary": "mpv",
        "cache_enabled": True,
        "cache_secs": 90,
        "demuxer_max_bytes": "128MiB",
        "demuxer_max_back_bytes": "32MiB",
        "audio_buffer": 1.2,
        "msg_level": "",
    },
    "logging": {"level": "INFO"},
    "server": {"cors_allow_origins": "*", "public_base_url": "", "enable_https_redirect": False, "http_request_timeout": 10},
    "chromecast": {"discovery_timeout": 3, "wait_timeout": 10},
}

SECRET_KEYS = {("subsonic", "password")}

VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Which sections can be applied live vs. need a service restart
SECTION_APPLIES = {
    "logging": "live",
    "subsonic": "restart",
    "mpv": "restart",
    "server": "restart",
    "speakers": "live",  # live since Phase B: add/remove applies without restart
}


class ConfigStoreService:
    """Persistent operational configuration: JSON file, atomic writes."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.getenv("CONFIG_FILE", os.path.join("data", "config.json"))
        self._data: Dict[str, Any] = {}
        self.load()

    # --- loading / persistence -------------------------------------------------
    def load(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            logger.info("Config store not present yet (%s) — starting from defaults", self.path)
        except Exception as e:
            logger.error("Config store unreadable (%s): %s — starting from defaults", self.path, e)
        if not isinstance(data, dict):
            data = {}

        data["version"] = SCHEMA_VERSION
        for section, defaults in SECTION_DEFAULTS.items():
            if not isinstance(defaults, dict):
                continue  # list-typed sections (speakers) validated separately
            current = data.get(section, {})
            if not isinstance(current, dict):
                current = {}
            merged = dict(defaults)
            merged.update({k: v for k, v in current.items() if k in defaults})
            data[section] = merged

        raw_speakers = data.get("speakers")
        speakers = []
        if isinstance(raw_speakers, list):
            for entry in raw_speakers:
                if isinstance(entry, dict) and entry.get("name") and entry.get("backend"):
                    speakers.append({
                        "name": str(entry["name"]).strip().lower(),
                        "backend": str(entry["backend"]).strip().lower(),
                        "options": entry.get("options") if isinstance(entry.get("options"), dict) else {},
                        "is_default": bool(entry.get("is_default")),
                        "display_name": str(entry.get("display_name") or "").strip(),
                    })
        data["speakers"] = speakers

        self._data = data
        return data

    def save(self) -> None:
        """Atomic write (tmp + rename), file permissions 0600 — secrets live here."""
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".config-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
                fh.write("\n")
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self.path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        logger.info("Config store saved: %s", self.path)

    # --- access ----------------------------------------------------------------
    @property
    def data(self) -> Dict[str, Any]:
        return self._data

    def section(self, name: str) -> Any:
        return self._data.get(name, SECTION_DEFAULTS.get(name, {}))

    def update_section(self, name: str, values: Dict[str, Any]) -> Dict[str, Any]:
        """Merge allowed keys of a dict-section and persist. Unknown keys ignored."""
        allowed = SECTION_DEFAULTS.get(name, {})
        if not allowed:
            raise ValueError(f"Unknown config section: {name}")
        merged = dict(self.section(name))
        for key, value in (values or {}).items():
            if key not in allowed:
                continue
            if (name, key) in SECRET_KEYS and (value is None or value == ""):
                continue  # blank never overwrites a stored secret
            merged[key] = value
        self._data[name] = merged
        self.save()
        return merged

    def set_speakers(self, speakers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cleaned = []
        for entry in speakers or []:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            cleaned.append({
                "name": str(entry["name"]).strip().lower(),
                "backend": str(entry.get("backend", "chromecast")).strip().lower(),
                "options": entry.get("options") if isinstance(entry.get("options"), dict) else {},
                "is_default": bool(entry.get("is_default")),
                "display_name": str(entry.get("display_name") or "").strip(),
            })
        self._data["speakers"] = cleaned
        self.save()
        return cleaned

    # --- speaker list management (Phase B: live speaker manager) -----------------
    def add_speaker(self, name: str, backend: str = "chromecast",
                    options: Optional[Dict[str, Any]] = None,
                    is_default: bool = False,
                    display_name: str = "") -> List[Dict[str, Any]]:
        """Add one speaker to the store. Raises ValueError on empty/duplicate
        names; an added default clears the previous one (single default).
        display_name is an optional free-text label shown in the UI."""
        clean = str(name or "").strip().lower()
        if not clean:
            raise ValueError("Speaker name is required")
        speakers = list(self.section("speakers"))
        if any(s["name"] == clean for s in speakers):
            raise ValueError(f"Speaker '{clean}' is already configured")
        if is_default:
            for s in speakers:
                s["is_default"] = False
        speakers.append({
            "name": clean,
            "backend": (backend or "chromecast").strip().lower(),
            "options": dict(options or {}),
            "is_default": bool(is_default),
            "display_name": str(display_name or "").strip(),
        })
        self._data["speakers"] = speakers
        self.save()
        return speakers

    def remove_speaker(self, name: str) -> List[Dict[str, Any]]:
        """Remove one speaker from the store. Raises ValueError if unknown.
        If the removed speaker was the default, the first remaining one is
        promoted so the store always has a deterministic default."""
        clean = str(name or "").strip().lower()
        speakers = list(self.section("speakers"))
        remaining = [s for s in speakers if s["name"] != clean]
        if len(remaining) == len(speakers):
            raise ValueError(f"Speaker '{clean}' is not configured")
        removed_was_default = any(s["name"] == clean and s.get("is_default") for s in speakers)
        if removed_was_default and remaining:
            remaining[0]["is_default"] = True
        self._data["speakers"] = remaining
        self.save()
        return remaining

    def set_default_speaker(self, name: str) -> List[Dict[str, Any]]:
        """Flag exactly one configured speaker as default."""
        clean = str(name or "").strip().lower()
        speakers = list(self.section("speakers"))
        if not any(s["name"] == clean for s in speakers):
            raise ValueError(f"Speaker '{clean}' is not configured")
        for s in speakers:
            s["is_default"] = s["name"] == clean
        self._data["speakers"] = speakers
        self.save()
        return speakers

    def set_speaker_display_name(self, name: str, display_name: str) -> List[Dict[str, Any]]:
        """Set (or clear, with an empty value) a speaker's UI display label.
        The technical name stays the matching key; display_name is cosmetic."""
        clean = str(name or "").strip().lower()
        speakers = list(self.section("speakers"))
        for s in speakers:
            if s["name"] == clean:
                s["display_name"] = str(display_name or "").strip()
                self._data["speakers"] = speakers
                self.save()
                return speakers
        raise ValueError(f"Speaker '{clean}' is not configured")


class ConfigService:
    """Merged effective configuration + runtime appliers.

    Precedence: code defaults <- config store <- (system env for boot keys only).
    """

    def __init__(self, store: ConfigStoreService, system_config):
        self.store = store
        self.system = system_config  # app.config.config — system/env keys

    # --- typed accessors -------------------------------------------------------
    def subsonic(self) -> Dict[str, Any]:
        return dict(self.store.section("subsonic"))

    def speakers(self) -> List[Dict[str, Any]]:
        return list(self.store.section("speakers"))

    def default_speaker_name(self) -> Optional[str]:
        for entry in self.speakers():
            if entry.get("is_default"):
                return entry["name"]
        first = self.speakers()
        return first[0]["name"] if first else None

    def mpv(self) -> Dict[str, Any]:
        return dict(self.store.section("mpv"))

    def logging_level(self) -> str:
        return str(self.store.section("logging").get("level") or "INFO").upper()

    def server(self) -> Dict[str, Any]:
        return dict(self.store.section("server"))

    def effective(self) -> Dict[str, Any]:
        """Full merged view, secrets masked, every key tagged with its source."""
        view: Dict[str, Any] = {"version": self.store.data.get("version"), "sections": {}}
        for section, defaults in SECTION_DEFAULTS.items():
            if section == "speakers":
                view["sections"][section] = {
                    "value": self.speakers(),
                    "source": "store" if self.store.section("speakers") else "empty",
                    "applies": "live",
                }
                continue
            store_section = dict(self.store.section(section))
            entry: Dict[str, Any] = {"source": "store", "applies": SECTION_APPLIES.get(section, "restart")}
            keys_view = {}
            for key, default_value in defaults.items():
                if (section, key) in SECRET_KEYS:
                    keys_view[key] = {
                        "value": "",
                        "masked": True,
                        "set": bool(store_section.get(key)),
                        "source": "store" if store_section.get(key) else "unset",
                    }
                else:
                    keys_view[key] = {
                        "value": store_section.get(key, default_value),
                        "source": "store" if key in store_section else "default",
                    }
            entry["keys"] = keys_view
            view["sections"][section] = entry
        # system/env-only keys, for visibility
        view["sections"]["system_env"] = {
            "keys": {
                "log_server_host": {"value": self.system.LOG_SERVER_HOST, "source": "env"},
                "log_server_port": {"value": self.system.LOG_SERVER_PORT, "source": "env"},
            },
            "source": "env",
            "applies": "restart",
        }
        return view

    def apply_runtime(self) -> Dict[str, str]:
        """Apply what can be applied without a restart. Returns what was applied."""
        level = self.logging_level()
        if level in VALID_LOG_LEVELS:
            logging.getLogger().setLevel(level)
            logger.info("Effective log level set to %s (live)", level)
        return {"logging": "live"}


class SubsonicConfigAdapter:
    """Duck-typed stand-in for the old config object, built from the store."""

    def __init__(self, config_service: ConfigService):
        sub = config_service.subsonic()
        self.SUBSONIC_URL = sub.get("url") or ""
        self.SUBSONIC_USER = sub.get("user") or ""
        self.SUBSONIC_PASS = sub.get("password") or ""
        self.SUBSONIC_CLIENT = sub.get("client") or "JukeboxPi"
        self.SUBSONIC_API_VERSION = sub.get("api_version") or "1.16.1"
        self.HTTP_REQUEST_TIMEOUT = int(config_service.store.section("server").get("http_request_timeout", 10))
        self.PUBLIC_BASE_URL = str(config_service.server().get("public_base_url") or "").rstrip("/")


def chromecast_config_view(config_service: "ConfigService"):
    """Chromecast timing view from the store (per-speaker overrides later)."""
    section = config_service.store.section("chromecast")
    return SimpleNamespace(
        CHROMECAST_DISCOVERY_TIMEOUT=int(section.get("discovery_timeout", 3)),
        CHROMECAST_WAIT_TIMEOUT=int(section.get("wait_timeout", 10)),
    )


def mpv_config_view(config_service: ConfigService, device_name: Optional[str],
                    options: Optional[Dict[str, Any]]):
    """Per-speaker MPV view: shared mpv defaults + speaker overrides."""
    shared = config_service.mpv()
    options = options or {}
    name = device_name or "mpv"
    socket = options.get("ipc_socket") or f"/tmp/jukebox-mpv-{name}.sock"
    return SimpleNamespace(
        MPV_DEVICE_NAME=options.get("device_name") or name.replace("_", " ").upper(),
        MPV_IPC_SOCKET=socket,
        MPV_LOG_FILE=options.get("log_file", ""),
        MPV_MSG_LEVEL=shared.get("msg_level", ""),
        MPV_CACHE_ENABLED=bool(shared.get("cache_enabled", True)),
        MPV_CACHE_SECS=int(shared.get("cache_secs", 90)),
        MPV_DEMUXER_MAX_BYTES=shared.get("demuxer_max_bytes", "128MiB"),
        MPV_DEMUXER_MAX_BACK_BYTES=shared.get("demuxer_max_back_bytes", "32MiB"),
        MPV_AUDIO_BUFFER_SECONDS=float(shared.get("audio_buffer", 1.2)),
        MPV_BINARY=shared.get("binary", "mpv"),
        MPV_EXTRA_ARGS="",
        MPV_STARTUP_TIMEOUT_SECONDS=int(shared.get("startup_timeout", 5)),
        # reserved for the USB-DAC backburner item
        MPV_AUDIO_DEVICE=options.get("audio_device") or "",
    )