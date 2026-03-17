"""
Custom StaticFiles middleware with explicit MIME type handling.
Ensures JavaScript files are served with correct Content-Type headers.
"""

from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.types import Receive, Scope, Send
import os


class CustomStaticFiles(StaticFiles):
    """
    Extended StaticFiles that ensures correct MIME types for web assets.
    
    This fixes issues where Python's mimetypes module might not correctly
    identify JavaScript files, especially on macOS or systems with unusual
    MIME type configurations.
    """
    
    # Explicit MIME type mappings for common web assets
    MIME_TYPES = {
        '.js': 'application/javascript',
        '.mjs': 'application/javascript',
        '.json': 'application/json',
        '.css': 'text/css',
        '.html': 'text/html',
        '.htm': 'text/html',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.svg': 'image/svg+xml',
        '.ico': 'image/x-icon',
        '.woff': 'font/woff',
        '.woff2': 'font/woff2',
        '.ttf': 'font/ttf',
        '.eot': 'application/vnd.ms-fontobject',
        '.otf': 'font/otf',
        '.webp': 'image/webp',
        '.xml': 'application/xml',
        '.txt': 'text/plain',
        '.pdf': 'application/pdf',
        '.zip': 'application/zip',
        '.mp3': 'audio/mpeg',
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.ogg': 'audio/ogg',
        '.wav': 'audio/wav',
    }
    
    def _get_mime_type(self, path: str) -> str:
        """Get MIME type for a file path using our explicit mappings."""
        _, ext = os.path.splitext(path)
        return self.MIME_TYPES.get(ext.lower(), 'application/octet-stream')
    
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        Override to intercept responses and fix Content-Type headers.
        """
        if scope["type"] != "http":
            await super().__call__(scope, receive, send)
            return
        
        # Get the requested path
        path = scope.get("path", "")
        
        # Determine the correct MIME type
        correct_mime_type = self._get_mime_type(path)
        
        async def send_wrapper(message):
            """Wrapper to modify the Content-Type header."""
            if message["type"] == "http.response.start":
                # Convert headers list to dict, modify, convert back
                headers = dict(message.get("headers", []))
                # Override the content-type header (lowercase key)
                headers[b"content-type"] = correct_mime_type.encode("utf-8")
                # Convert back to list of tuples
                message["headers"] = [(k, v) for k, v in headers.items()]
            await send(message)
        
        await super().__call__(scope, receive, send_wrapper)
