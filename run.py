#!/usr/bin/env python3
"""
Jukeplayer Backend Server
Entry point for FastAPI backend application
"""

import logging
import sys

# Logging is configured inside app.main:app (setup_logging). Do not call
# setup_logging here as well — a second setup would wipe the first's handlers.

# Get logger; handlers may not exist yet, so keep import-time logging minimal
logger = logging.getLogger("run")
logger.info("Starting Jukebox Backend...")

import uvicorn


def main():
    """Main entry point"""
    # Log configuration details
    logger.info("=" * 60)
    logger.info("🚀 Jukebox Backend Starting")
    logger.info("=" * 60)
    logger.info(f"Log file: jukebox.log")
    logger.info(f"Console output: Enabled (sys.stdout)")
    logger.info(f"Syslog: Check your syslog server")
    logger.info("=" * 60)
    
    # Suppress uvicorn's default logging to prevent duplicates
    # Our setup_logging() already handles console/file/syslog output
    logging.getLogger("uvicorn.access").disabled = False
    logging.getLogger("uvicorn.error").disabled = False
    
    # Run uvicorn with minimal config (don't override our logging)
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_config=None,       # Use our custom logging, not uvicorn's
        log_level="info",
        access_log=False       # Keep off: app-level handlers cover syslog/file
    )


if __name__ == "__main__":
    main()
