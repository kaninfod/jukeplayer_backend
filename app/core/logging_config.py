import logging
import logging.handlers
import socket
import os
from app.config import config

def setup_logging(log_file="jukebox.log", level=logging.DEBUG):
    """Configure logging for the jukebox app with syslog + file fallback."""

    logger = logging.getLogger()
    logger.setLevel(level)

    hostname = socket.gethostname()
    formatter = logging.Formatter(f'{hostname} %(name)s: %(levelname)s %(message)s')

    # === SYSLOG HANDLER (Primary) ===
    syslog_configured = False
    if config.LOG_SERVER_HOST and config.LOG_SERVER_HOST.lower() not in ['localhost', '127.0.0.1', '']:
        try:
            syslog_address = (config.LOG_SERVER_HOST, config.LOG_SERVER_PORT)
            syslog_handler = logging.handlers.SysLogHandler(address=syslog_address)
            syslog_handler.setFormatter(formatter)
            logging.getLogger().addHandler(syslog_handler)
            syslog_configured = True
            logging.info(f"✅ Syslog configured: {config.LOG_SERVER_HOST}:{config.LOG_SERVER_PORT}")
        except Exception as e:
            logging.warning(f"⚠️  Syslog server unavailable ({config.LOG_SERVER_HOST}:{config.LOG_SERVER_PORT}): {e}")
            logging.info("   Falling back to file logging only")
    else:
        logging.debug("Syslog not configured (LOG_SERVER_HOST empty)")

    # === FILE HANDLER (Fallback/Always) ===
    try:
        os.makedirs("logs", exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logging.getLogger().addHandler(file_handler)
    except Exception as e:
        logging.warning(f"Could not create log file: {e}")

    # === CONSOLE HANDLER (Always) ===
    screen_handler = logging.StreamHandler()
    screen_handler.setFormatter(formatter)
    logging.getLogger().addHandler(screen_handler)
    
    # === SUPPRESS NOISY THIRD-PARTY LOGS ===
    for lib in ["requests", "PIL", "urllib3", "pychromecast", "httpcore"]:
        logging.getLogger(lib).setLevel(logging.WARNING)
    
    # Suppress websockets, starlette, and uvicorn debug logs (PING/PONG frames are very noisy)
    for lib in ["websockets", "websockets.protocol", "websockets.frames", "websockets.client", 
                "websockets.server", "starlette", "uvicorn", "uvicorn.protocols"]:
        logging.getLogger(lib).setLevel(logging.ERROR)



