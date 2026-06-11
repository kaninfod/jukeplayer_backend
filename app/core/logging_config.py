import logging
import logging.handlers
import socket
import os
from app.config import config

def setup_logging(log_file="jukebox.log", level=logging.DEBUG):
    """Configure logging for the jukebox app with syslog + file fallback."""

    # 1. TRULY clear everything attached to the root logger first
    # This wipes out Uvicorn defaults and previous setups cleanly.
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
        
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    hostname = socket.gethostname()
    formatter = logging.Formatter(f'{hostname} %(name)s: %(levelname)s %(message)s')

    # Arrays to hold strings we want to log AFTER setup is done
    # This prevents triggering Python's default basicConfig() prematurely!
    delayed_logs = []

    # === SYSLOG HANDLER (Primary) ===
    syslog_configured = False
    if config.LOG_SERVER_HOST and config.LOG_SERVER_HOST.lower() not in ['localhost', '127.0.0.1', '']:
        try:
            syslog_address = (config.LOG_SERVER_HOST, config.LOG_SERVER_PORT)
            syslog_handler = logging.handlers.SysLogHandler(address=syslog_address)
            syslog_handler.setFormatter(formatter)
            root_logger.addHandler(syslog_handler)
            syslog_configured = True
            delayed_logs.append(("info", f"✅ Syslog configured: {config.LOG_SERVER_HOST}:{config.LOG_SERVER_PORT}"))
        except Exception as e:
            delayed_logs.append(("warning", f"⚠️  Syslog server unavailable ({config.LOG_SERVER_HOST}:{config.LOG_SERVER_PORT}): {e}"))
            delayed_logs.append(("info", "   Falling back to file logging only"))
    else:
        delayed_logs.append(("debug", "Syslog not configured (LOG_SERVER_HOST empty)"))

    # === FILE HANDLER (Fallback/Always) ===
    try:
        os.makedirs("logs", exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        delayed_logs.append(("warning", f"Could not create log file: {e}"))

    # === CONSOLE HANDLER (Dev only) ===
    screen_handler = logging.StreamHandler()
    screen_handler.setFormatter(formatter)
    root_logger.addHandler(screen_handler)
    
    # === SUPPRESS NOISY THIRD-PARTY LOGS ===
    for lib in ["requests", "PIL", "urllib3", "pychromecast", "httpcore"]:
        logging.getLogger(lib).setLevel(logging.WARNING)
    
    for lib in ["websockets", "websockets.protocol", "websockets.frames", "websockets.client", 
                "websockets.server", "starlette", "uvicorn", "uvicorn.protocols"]:
        logging.getLogger(lib).setLevel(logging.ERROR)

    # 2. Now that handlers are safely attached, flush our startup logs safely!
    setup_logger = logging.getLogger("logging_setup")
    for level_str, msg in delayed_logs:
        getattr(setup_logger, level_str)(msg)


# def setup_logging(log_file="jukebox.log", level=logging.DEBUG):
#     """Configure logging for the jukebox app with syslog + file fallback."""

#     logger = logging.getLogger()
    
#     # Remove any existing handlers to prevent duplicate logging
#     if logger.hasHandlers():
#         logger.handlers.clear()
        
#     logger.setLevel(level)

#     hostname = socket.gethostname()
#     formatter = logging.Formatter(f'{hostname} %(name)s: %(levelname)s %(message)s')

#     # === SYSLOG HANDLER (Primary) ===
#     syslog_configured = False
#     if config.LOG_SERVER_HOST and config.LOG_SERVER_HOST.lower() not in ['localhost', '127.0.0.1', '']:
#         try:
#             syslog_address = (config.LOG_SERVER_HOST, config.LOG_SERVER_PORT)
#             syslog_handler = logging.handlers.SysLogHandler(address=syslog_address)
#             syslog_handler.setFormatter(formatter)
#             logging.getLogger().addHandler(syslog_handler)
#             syslog_configured = True
#             logging.info(f"✅ Syslog configured: {config.LOG_SERVER_HOST}:{config.LOG_SERVER_PORT}")
#         except Exception as e:
#             logging.warning(f"⚠️  Syslog server unavailable ({config.LOG_SERVER_HOST}:{config.LOG_SERVER_PORT}): {e}")
#             logging.info("   Falling back to file logging only")
#     else:
#         logging.debug("Syslog not configured (LOG_SERVER_HOST empty)")

#     # === FILE HANDLER (Fallback/Always) ===
#     try:
#         os.makedirs("logs", exist_ok=True)
#         file_handler = logging.FileHandler(log_file)
#         file_handler.setFormatter(formatter)
#         logging.getLogger().addHandler(file_handler)
#     except Exception as e:
#         logging.warning(f"Could not create log file: {e}")

#     # === CONSOLE HANDLER (Dev only) ===
#     screen_handler = logging.StreamHandler()
#     screen_handler.setFormatter(formatter)
#     logging.getLogger().addHandler(screen_handler)
    
#     # === SUPPRESS NOISY THIRD-PARTY LOGS ===
#     for lib in ["requests", "PIL", "urllib3", "pychromecast", "httpcore"]:
#         logging.getLogger(lib).setLevel(logging.WARNING)
    
#     # Suppress websockets, starlette, and uvicorn debug logs (PING/PONG frames are very noisy)
#     for lib in ["websockets", "websockets.protocol", "websockets.frames", "websockets.client", 
#                 "websockets.server", "starlette", "uvicorn", "uvicorn.protocols"]:
#         logging.getLogger(lib).setLevel(logging.ERROR)



