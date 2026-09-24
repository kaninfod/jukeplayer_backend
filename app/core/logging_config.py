import logging
import logging.handlers
import socket
import os
from app.config import config

# Log file lives under logs/ (rotated). Honors LOG_FILE env var when set.
DEFAULT_LOG_FILE = os.getenv("LOG_FILE", "logs/jukebox.log")

def boot_log_level():
    """Boot-time log level: the config store's logging.level wins, then
    LOG_LEVEL env, then INFO. Direct file read (no services exist yet)."""
    import json
    store_path = os.getenv("CONFIG_FILE", os.path.join("data", "config.json"))
    try:
        with open(store_path, "r", encoding="utf-8") as fh:
            level = str(json.load(fh).get("logging", {}).get("level", "")).upper()
        if level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            return getattr(logging, level)
    except Exception:
        pass
    return getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)

def setup_logging(log_file=None, level=logging.INFO):
    """Configure logging: RFC3164 directly to syslog (real PRI severity per
    record), plus container-local file and console handlers. The Docker
    syslog driver is deliberately NOT used — the app owns its syslog identity
    (facility local0, tag jukeplayer_backend, hostname jukeplayer-backend)."""
    if not log_file:
        log_file = DEFAULT_LOG_FILE

    # 1. TRULY clear everything attached to the root logger first
    # This wipes out Uvicorn defaults and previous setups cleanly.
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    hostname = socket.gethostname()          # "jukeplayer-backend" via compose
    tag = "jukeplayer_backend"               # the app type (mirrors jukeplayer_esp32)

    formatter = logging.Formatter(
        f"%(asctime)s {hostname} {tag}: [%(levelname)s] %(name)s: %(message)s",
        datefmt="%b %d %H:%M:%S",
    )

    # Arrays to hold strings we want to log AFTER setup is done
    # This prevents triggering Python's default basicConfig() prematurely!
    delayed_logs = []

    # === SYSLOG HANDLER (Primary) — the ONLY syslog path ===
    # Python maps the real record level into the PRI (DEBUG→7 … CRITICAL→2),
    # so severity is filterable server-side without parsing the message.
    syslog_configured = False
    if config.LOG_SERVER_HOST and config.LOG_SERVER_HOST.lower() not in ["localhost", "127.0.0.1", ""]:
        try:
            syslog_address = (config.LOG_SERVER_HOST, config.LOG_SERVER_PORT)
            syslog_handler = logging.handlers.SysLogHandler(
                address=syslog_address,
                facility=logging.handlers.SysLogHandler.LOG_LOCAL0,
            )
            syslog_handler.setFormatter(formatter)
            root_logger.addHandler(syslog_handler)
            syslog_configured = True
            delayed_logs.append(("info", f"✅ [SYSLOG] configured: {config.LOG_SERVER_HOST}:{config.LOG_SERVER_PORT} (facility local0)"))
        except Exception as e:
            delayed_logs.append(("warning", f"⚠️  [SYSLOG] server unavailable ({config.LOG_SERVER_HOST}:{config.LOG_SERVER_PORT}): {e}"))
            delayed_logs.append(("info", "   Falling back to file logging only"))
    else:
        delayed_logs.append(("debug", "[SYSLOG] not configured (LOG_SERVER_HOST empty)"))

    # === FILE HANDLER (container-local, rotated) ===
    try:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        delayed_logs.append(("warning", f"[FILE] could not create log file: {e}"))

    # === CONSOLE HANDLER (stdout — visible via `docker logs`, NOT syslog) ===
    screen_handler = logging.StreamHandler()
    screen_handler.setFormatter(formatter)
    root_logger.addHandler(screen_handler)

    # === SUPPRESS NOISY THIRD-PARTY LOGS ===
    for lib in ["requests", "PIL", "urllib3", "pychromecast", "httpcore", "asyncio"]:
        logging.getLogger(lib).setLevel(logging.WARNING)

    for lib in ["websockets", "websockets.protocol", "websockets.frames", "websockets.client",
                "websockets.server", "starlette", "uvicorn", "uvicorn.protocols"]:
        logging.getLogger(lib).setLevel(logging.ERROR)

    # 2. Now that handlers are safely attached, flush our startup logs safely!
    setup_logger = logging.getLogger("logging_setup")
    for level_str, msg in delayed_logs:
        getattr(setup_logger, level_str)(msg)