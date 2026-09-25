"""Cast target matching (Phase D, running-list item 8).

The old connect path compared the normalized store name against the device's
friendly name with an EXACT string compare — so cast GROUPS never matched
(store 'home_group' → 'Home Group' vs device-reported 'Home group') and
playback to group speakers always failed with "not found on network".

The fix: UUID-first matching (stored in speaker options at add time), then a
case/whitespace-insensitive name fold.
"""
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

import app.playback_backends.chromecast as cc
from app.playback_backends.chromecast import ChromecastService, _target_matches


def test_uuid_match_wins_over_name():
    """Exact UUID match matches regardless of what the friendly name says."""
    assert _target_matches("Anything Else", "uuid-A", "Whatever Name", "uuid-A")
    # uuid mismatch falls back to the (folded) name match — OR semantics
    assert _target_matches("Home Group", "uuid-A", "Home group", "uuid-B")
    # neither uuid nor (folded) name match → no match
    assert not _target_matches("Bedroom", "uuid-A", "Home group", "uuid-B")


def test_name_match_folds_case_and_whitespace():
    """Cast groups: device reports 'Home group', store name normalizes to
    'Home Group' — case/spacing must not matter."""
    assert _target_matches("Home group", "u1", "Home Group", None)
    assert _target_matches("Home  Group", "u1", "Home Group", None)   # double space
    assert _target_matches("  Home group ", "u1", "Home Group", None)  # stray spaces
    assert _target_matches("Bedroom", "u1", "Home Group", None) is False


def test_no_target_matches_nothing():
    assert _target_matches("Kitchen", "u1", None, None) is False


def test_cast_uuid_read_from_options(monkeypatch):
    """Speaker options carry cast_uuid (stored at add time); None/empty → None."""
    monkeypatch.setattr(cc, "_get_global_browser", lambda: MagicMock())
    svc = ChromecastService("home_group",
                            config_view=SimpleNamespace(CHROMECAST_DISCOVERY_TIMEOUT=3,
                                                        CHROMECAST_WAIT_TIMEOUT=10),
                            options={"cast_uuid": "abc-123"})
    assert svc.cast_uuid == "abc-123"

    bare = ChromecastService("home_group",
                             config_view=SimpleNamespace(CHROMECAST_DISCOVERY_TIMEOUT=3,
                                                         CHROMECAST_WAIT_TIMEOUT=10),
                             options=None)
    assert bare.cast_uuid is None

    empty = ChromecastService("home_group",
                              config_view=SimpleNamespace(CHROMECAST_DISCOVERY_TIMEOUT=3,
                                                          CHROMECAST_WAIT_TIMEOUT=10),
                              options={"cast_uuid": "  "})
    assert empty.cast_uuid is None


def test_connect_passes_stored_uuid(monkeypatch):
    """connect() hands the stored cast_uuid to discovery for robust matching."""
    svc = ChromecastService.__new__(ChromecastService)
    svc.device_name = "home_group"
    svc.cast_uuid = "abc-123"
    svc.cast = None
    svc.mc = None
    svc.status_listener = None

    captured = {}
    monkeypatch.setattr(svc, "_discover_chromecasts",
                        lambda timeout=None, target_name=None, target_uuid=None:
                        captured.update(target_name=target_name, target_uuid=target_uuid)
                        or ([], None, {}))
    import app.playback_backends.chromecast as mod
    monkeypatch.setattr(mod.pychromecast, "get_chromecast_from_cast_info", MagicMock())

    assert svc.connect(device_name="home_group") is False  # not found, no connection
    assert captured == {"target_name": "Home Group", "target_uuid": "abc-123"}