#!/usr/bin/env python3
"""
Jukeplayer Backend Server
Entry point for FastAPI backend application
"""

import logging
import sys
from app.core.logging_config import setup_logging

# Initialize logging FIRST, before any other imports
setup_logging(log_file="jukebox.log", level=logging.DEBUG)

# Get logger after setup
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
    
    # Run uvicorn with minimal config (don't override our logging)
    # Use log_level="info" so uvicorn doesn't spam debug logs
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_config=None,  # Use our custom logging, not uvicorn's
        log_level="debug",  # Uvicorn's own logs at debug level
        access_log=False  # Don't spam HTTP access logs
    )


if __name__ == "__main__":
    main()
