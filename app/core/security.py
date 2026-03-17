from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable, Awaitable
import logging
import base64

from app.config import config

logger = logging.getLogger(__name__)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    Middleware to protect all /api/* routes using an API key or Basic Auth.

    Behavior:
    - Localhost (127.0.0.1, ::1) bypass if ALLOW_LOCAL_API_BYPASS is true
    - Accept X-API-Key header or Authorization: Bearer <token>
    - Accept Authorization: Basic <credentials> if WEB_BASIC_AUTH_USER/PASS configured
    - Otherwise return 401
    """

    def __init__(self, app):
        super().__init__(app)
        self._localhost_hosts = {"127.0.0.1", "::1"}
        # Add local network IPs for bypass when ALLOW_LOCAL_API_BYPASS is true
        self._local_network_prefixes = ("192.168.", "10.", "172.16.")

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable]):
        path = request.url.path
        # Only protect API routes
        if not path.startswith("/api/"):
            return await call_next(request)

        client_host = (request.client.host if request.client else None)

        # Allow localhost and local network IPs if enabled
        if config.ALLOW_LOCAL_API_BYPASS and client_host:
            if client_host in self._localhost_hosts:
                return await call_next(request)
            # Check if it's a local network IP
            if any(client_host.startswith(prefix) for prefix in self._local_network_prefixes):
                return await call_next(request)

        # Check for API key first (preferred method)
        if config.API_KEY:
            # Accept either custom header X-API-Key or Authorization: Bearer <token>
            api_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
            if not api_key:
                auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
                if auth_header and isinstance(auth_header, str):
                    parts = auth_header.split(" ", 1)
                    if len(parts) == 2:
                        if parts[0].lower() == "bearer":
                            api_key = parts[1]
                        elif parts[0].lower() == "basic":
                            # Try Basic Auth as fallback
                            if config.WEB_BASIC_AUTH_USER and config.WEB_BASIC_AUTH_PASS:
                                if self._validate_basic_auth(parts[1]):
                                    return await call_next(request)
            
            if api_key and api_key == config.API_KEY:
                return await call_next(request)
            
            # Neither API key nor valid Basic Auth
            logger.warning(f"API authentication failed for {request.method} {path} from {client_host}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized: missing or invalid API key"}
            )

        # No API key set and not localhost: deny
        logger.warning(f"API request denied: no API_KEY configured, request from {client_host} to {path}")
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized: API disabled for public access without API_KEY"}
        )
    
    def _validate_basic_auth(self, encoded_credentials: str) -> bool:
        """Validate Basic Auth credentials"""
        try:
            decoded = base64.b64decode(encoded_credentials).decode('utf-8')
            username, password = decoded.split(':', 1)
            return (username == config.WEB_BASIC_AUTH_USER and 
                    password == config.WEB_BASIC_AUTH_PASS)
        except Exception as e:
            logger.debug(f"Basic auth validation failed: {e}")
            return False
