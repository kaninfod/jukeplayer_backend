from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from fastapi.responses import Response
from urllib.parse import urlparse
from app.config import config


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Lightweight middleware to add common security headers to every response.
    Adjust CSP if you serve external resources.
    """

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("x-frame-options", "DENY")
        response.headers.setdefault("referrer-policy", "no-referrer")

        # Build a CSP that allows images from self, data:, and (optionally) the Subsonic/Gonic host
        img_sources = ["'self'", "data:"]
        # Defaults for style/script sources; extended conditionally below
        style_sources = ["'self'", "'unsafe-inline'", "data:"]
        script_sources = ["'self'", "'unsafe-inline'"]

        # Helper to robustly extract a host from either a URL or a bare hostname
        def _extract_host(value: str) -> str:
            try:
                if not value:
                    return ""
                parsed = urlparse(value)
                host = parsed.netloc
                if not host:
                    # If no scheme was provided (bare hostname), try parsing with // prefix
                    parsed2 = urlparse(f"//{value}")
                    host = parsed2.netloc or value.split('/')[0]
                # Strip credentials if any (user:pass@host)
                if '@' in host:
                    host = host.split('@', 1)[1]
                # Remove trailing port if present for CSP host entries
                if ':' in host:
                    host = host.split(':', 1)[0]
                return host
            except Exception:
                return ""

        try:
            subsonic = getattr(config, "SUBSONIC_URL", None)
            host = _extract_host(subsonic)
            if host:
                # Allow either scheme explicitly to be safe with redirects/cert offload
                img_sources.append(f"https://{host}")
                img_sources.append(f"http://{host}")
        except Exception:
            # Fall back to defaults if parsing fails
            pass

        # Also allow the PUBLIC_BASE_URL host (used to generate absolute cover URLs for Chromecast/UI)
        try:
            public_base = getattr(config, "PUBLIC_BASE_URL", None)
            host = _extract_host(public_base)
            if host:
                img_sources.append(f"https://{host}")
                img_sources.append(f"http://{host}")
        except Exception:
            pass

        # If API docs are enabled, allow Swagger UI assets from CDN
        try:
            if getattr(config, "ENABLE_DOCS", False):
                # Swagger UI defaults to jsdelivr CDN; also allow unpkg to be safe across versions
                cdn_hosts = ["https://cdn.jsdelivr.net", "https://unpkg.com"]
                style_sources.extend(cdn_hosts)
                script_sources.extend(cdn_hosts)
                # Some Swagger UI builds use eval for client-side templating; allow only when docs enabled
                script_sources.append("'unsafe-eval'")
                # FastAPI docs favicon is served from fastapi.tiangolo.com
                img_sources.append("https://fastapi.tiangolo.com")
        except Exception:
            pass

        csp = (
            "default-src 'self' data:; "
            f"img-src {' '.join(img_sources)}; "
            f"style-src {' '.join(style_sources)}; "
            f"script-src {' '.join(script_sources)}; "
            "font-src 'self' data:"
        )

        response.headers.setdefault("content-security-policy", csp)
        # HSTS only matters over HTTPS; harmless over HTTP but only effective on HTTPS.
        response.headers.setdefault("strict-transport-security", "max-age=31536000; includeSubDomains; preload")
        return response
