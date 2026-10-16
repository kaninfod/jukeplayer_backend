"""The subsonic transport: token params + the request with its retry policy.
Extracted verbatim from the old app/services/subsonic_service.py — the
behaviour (one transient retry with a short backoff; HTTP errors raised) is
the tested contract."""
import hashlib
import random
import string
import time
from typing import Any, Dict, Optional

import requests

import logging

logger = logging.getLogger(__name__)


class SubsonicAPI:
    def __init__(self, config=None):
        if config:
            self.config = config
        else:
            # Fallback for backward compatibility — kept from the old class
            from app.config import config as default_config
            self.config = default_config

        self.base_url = self.config.SUBSONIC_URL.rstrip("/")
        self.username = getattr(self.config, "SUBSONIC_USER", "jukebox")
        self.password = getattr(self.config, "SUBSONIC_PASS", "123jukepi")
        self.client = getattr(self.config, "SUBSONIC_CLIENT", "jukebox")
        self.api_version = getattr(self.config, "SUBSONIC_API_VERSION", "1.16.1")
        logger.info(f"SubsonicAPI initialized for {self.base_url} as {self.username}")

    def _api_params(self) -> Dict[str, str]:
        salt = "".join(random.choices(string.ascii_letters + string.digits, k=8))
        token = hashlib.md5((self.password + salt).encode("utf-8")).hexdigest()
        return {
            "u": self.username,
            "t": token,
            "s": salt,
            "c": self.client,
            "v": self.api_version,
            "f": "json",
        }

    def _api_request(self, endpoint: str, extra_params: Optional[Dict[str, str]] = None,
                     retries: int = 1) -> requests.Response:
        """GET a Subsonic endpoint. Transient failures (connection reset,
        timeout) are retried once with a short backoff; HTTP errors are not."""
        params = self._api_params()
        if extra_params:
            params.update(extra_params)
        url = f"{self.base_url}/rest/{endpoint}"
        logger.debug(f"SubsonicService: Requesting {url}")

        last_transient_exc = None
        for attempt in range(retries + 1):
            try:
                resp = requests.get(url, params=params, timeout=self.config.HTTP_REQUEST_TIMEOUT)
                resp.raise_for_status()  # Raises HTTPError for bad status codes
                return resp
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                # Transient: RemoteDisconnected, read timeouts, connection resets
                last_transient_exc = e
                if attempt < retries:
                    logger.warning(f"⚠️  Subsonic {endpoint} transient error (attempt {attempt + 1}/{retries + 1}): {e} — retrying")
                    time.sleep(0.5)
                    continue
            except requests.exceptions.HTTPError as e:
                logger.error(f"❌ Subsonic HTTP error for {endpoint}: {e.response.status_code} {e.response.text[:200]}", exc_info=True)
                raise
            except Exception as e:
                logger.error(f"❌ Subsonic request failed for {endpoint}: {e}", exc_info=True)
                raise

        logger.error(f"❌ Subsonic {endpoint} failed after {retries + 1} attempts: {last_transient_exc}", exc_info=True)
        raise last_transient_exc