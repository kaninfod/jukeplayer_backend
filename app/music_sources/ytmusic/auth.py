"""YouTube Music auth: the Google TV-device OAuth flow via ytmusicapi.

The user's GCP client (client_id/secret from the YouTube Data API console,
"TVs and Limited Input devices" — the user knows this console dance) lives
in the config store's `sources.ytmusic` section; the flow:

  start()    → {verification_url, user_code} — the user opens the url on any
               browser, types the user_code, authorizes
  complete() → exchanges the device_code for the refreshable token dict
               (access_token/refresh_token/expires_at…) — the CALLER
               persists it into the config store (oauth.json's equivalent)
  YTMusic's client then refreshes silently from the stored token.
"""
import logging
from ytmusicapi import OAuthCredentials

logger = logging.getLogger(__name__)


class PendingGrant(RuntimeError):
    """Google says 'not yet' (authorization_pending / slow_down) — the
    caller keeps polling; this is not a failure."""


class YTMusicAuth:
    def __init__(self, client_id: str, client_secret: str):
        if not (client_id and client_secret):
            raise ValueError("ytmusic OAuth needs client_id and client_secret (the GCP 'TVs and Limited Input devices' client)")
        self._creds = OAuthCredentials(client_id=client_id, client_secret=client_secret)

    def start(self) -> dict:
        """Ask Google for the device-flow codes (AuthCodeDict)."""
        return self._creds.get_code()

    def complete(self, device_code: str) -> dict:
        """Exchange the (authorized) device_code for the refreshable token.

        ytmusicapi's token_from_code does NOT raise for a not-yet-authorized
        device code — it RETURNS the error dict ('authorization_pending').
        This normalizes that: PendingGrant while waiting, ValueError on
        denial/expiry, and ONLY a token-carrying dict on a real grant — the
        stored 'token' can never hold a wait-notice (the 2026-10-16
        first-add bug was exactly that shape)."""
        token = dict(self._creds.token_from_code(device_code))
        if token.get("error"):
            err = token["error"]
            if err in ("authorization_pending", "slow_down"):
                raise PendingGrant(err)
            raise ValueError(f"device flow ended without a grant: {err} ({token.get('error_description', '')})")
        for key in ("access_token", "refresh_token", "scope", "token_type"):
            if not token.get(key):
                raise ValueError(f"grant response missing '{key}' — refusing to store an incomplete token")
        return token