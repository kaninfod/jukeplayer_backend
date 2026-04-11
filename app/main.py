# Backend server - GPIO not needed. All hardware is handled by Pi client.
# This allows the backend to run on any platform (Mac, Linux, Docker, etc.)

import logging
import os
from app.core.logging_config import setup_logging

# Setup logging FIRST, before importing anything else that might log
setup_logging(level=logging.DEBUG)

import getpass
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

from app.config import config
from app.core.security_headers import SecurityHeadersMiddleware

logger = logging.getLogger(__name__)

#from app.routes.albums import router as album_router
from app.routes.mediaplayer import router as mediaplayer_router
from app.routes.mediaplayer import wsrouter as wsmediaplayer_router
from app.routes.system import router as system_router
from app.routes.subsonic import router as subsonic_router
#from app.routes.chromecast import router as chromecast_router
from app.routes.output import router as output_router
from app.routes.nfc_encoding import router as nfc_encoding_router


# Import services to ensure event subscriptions are active

from app.web.routes import router as web_router


# Initialize FastAPI app

# Enable interactive API docs when DEBUG_MODE=true or ENABLE_DOCS=true
enable_docs = getattr(config, "ENABLE_DOCS", False) or config.DEBUG_MODE
app = FastAPI(
    docs_url=(config.DOCS_URL if enable_docs else None),
    redoc_url=None,
    openapi_url=(config.OPENAPI_URL if enable_docs else None),
)

# Optional HTTP -> HTTPS redirect
if config.ENABLE_HTTPS_REDIRECT:
    app.add_middleware(HTTPSRedirectMiddleware)

# Add CORS middleware
cors_origins = [o.strip() for o in config.CORS_ALLOW_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Security: API key protection removed for local-only setup
# (APIKeyMiddleware was here)

# Add common security headers
app.add_middleware(SecurityHeadersMiddleware)

# Mount static directories for web access
album_cover_dir = config.STATIC_FILE_PATH
if not os.path.isabs(album_cover_dir):
    album_cover_dir = os.path.join(os.path.dirname(__file__), "..", album_cover_dir)
app.mount("/album_covers", StaticFiles(directory=album_cover_dir), name="album_covers")
app.mount("/assets", StaticFiles(directory=album_cover_dir), name="assets")


# === GLOBAL EXCEPTION HANDLER ===
# Catch and log all unhandled exceptions with full traceback
from fastapi.responses import JSONResponse
from starlette.requests import Request

@app.exception_handler(Exception)
def global_exception_handler(request: Request, exc: Exception):
    """Catch and log all exceptions that aren't caught by route handlers."""
    logger.error(
        f"Unhandled exception in {request.method} {request.url.path}: {type(exc).__name__}",
        exc_info=exc
    )
    
    # Return 500 error response
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
    )



# Include routers
# app.include_router(album_router)
app.include_router(mediaplayer_router)
app.include_router(system_router)
app.include_router(subsonic_router)
# app.include_router(chromecast_router)
app.include_router(output_router)
app.include_router(nfc_encoding_router)
app.include_router(web_router)
app.include_router(wsmediaplayer_router)
# Mount web static files (JS, CSS) - serve from app/web/static with proper MIME types
# MUST be mounted AFTER routers to avoid route conflicts
web_static_dir = os.path.join(os.path.dirname(__file__), "web", "static")
if os.path.isdir(web_static_dir):
    app.mount("/static", StaticFiles(directory=web_static_dir), name="web_static")
else:
    logger.warning(f"Web static directory not found: {web_static_dir}")

@app.on_event("startup")
async def startup_event():
    """Initialize all systems using the service container"""
    # Step 0: Validate configuration
    if not config.validate_config():
        logging.error("❌ Configuration validation failed. Please check your .env file.")
        return
    # Step 1: Setup service container
    from app.core.service_container import setup_service_container
    global_container = setup_service_container()
    # Step 2: Resolve all main services
    playback_service = global_container.get('playback_service')
    
    # Step 3: Setup WebSocket event dispatcher with the current event loop
    from app.websocket.event_dispatcher import setup_websocket_dispatcher
    from app.routes.mediaplayer import _get_data_for_current_track
    import asyncio
    current_loop = asyncio.get_running_loop()
    # Use the full data fetcher for now (can extend to support minimal in future)
    media_player_service = global_container.get('media_player_service')
    setup_websocket_dispatcher(
        track_fetcher=media_player_service.get_context,
        volume_fetcher=media_player_service.get_volume,
        event_loop=current_loop
    )

    import getpass, os
    logger.info(f"Running as user: {getpass.getuser()}")
    logger.info(f"PATH: {os.environ.get('PATH')}")
    logging.info("🚀Jukebox app startup complete")



@app.on_event("shutdown")
def shutdown_event():
    """Clean up resources on shutdown"""
    logging.info("Jukebox FastAPI app shutdown complete")