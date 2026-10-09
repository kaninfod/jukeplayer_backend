"""Unit tests for log-file resolution and the mpv log-level mapping."""
import logging
import os
from unittest.mock import patch

from app.core.logging_config import resolve_log_file


def test_default_file_when_env_unset():
    with patch.dict(os.environ, {}, clear=True):
        assert resolve_log_file() == "logs/jukebox.log"


def test_empty_env_disables_file_logging():
    with patch.dict(os.environ, {"LOG_FILE": ""}):
        assert resolve_log_file() is None


def test_env_path_wins_over_default():
    with patch.dict(os.environ, {"LOG_FILE": "custom/juke.log"}):
        assert resolve_log_file() == "custom/juke.log"


def test_caller_arg_wins_over_env():
    with patch.dict(os.environ, {"LOG_FILE": "custom/juke.log"}):
        assert resolve_log_file("explicit.log") == "explicit.log"


def test_mpv_log_level_map():
    from app.playback_backends.mpv import MPV_LOG_LEVEL_MAP
    assert MPV_LOG_LEVEL_MAP["fatal"] == logging.CRITICAL
    assert MPV_LOG_LEVEL_MAP["error"] == logging.ERROR
    assert MPV_LOG_LEVEL_MAP["warn"] == logging.WARNING
    assert MPV_LOG_LEVEL_MAP["info"] == logging.INFO
    # Levels we do not request (v/debug/trace) fall back to DEBUG
    assert MPV_LOG_LEVEL_MAP.get("v", logging.DEBUG) == logging.DEBUG

# === the syslog gate (tests never phone home to production Loki) ================

def test_syslog_gate_disables_handler(monkeypatch):
    """LOG_SYSLOG_ENABLED=0 → no SysLogHandler, even with LOG_SERVER_HOST set.
    (tests/conftest.py sets the gate; this test pins the mechanism itself.)"""
    import logging.handlers
    import app.config as app_config_mod
    from app.core.logging_config import setup_logging
    saved = logging.root.handlers[:]
    try:
        monkeypatch.setattr(app_config_mod.config, "LOG_SERVER_HOST", "192.168.68.102", raising=False)
        monkeypatch.setattr(app_config_mod.config, "LOG_SERVER_PORT", 514, raising=False)
        with patch.dict(os.environ, {"LOG_SYSLOG_ENABLED": "0"}):
            setup_logging()
        handlers = logging.root.handlers[:]
        assert not any(isinstance(h, logging.handlers.SysLogHandler) for h in handlers)
    finally:
        logging.root.handlers[:] = saved


def test_syslog_handler_present_when_gate_unset(monkeypatch):
    """Default behavior unchanged: with the gate unset and a LOG_SERVER_HOST
    configured, the SysLogHandler is installed exactly as before."""
    import logging.handlers
    import app.config as app_config_mod
    from app.core.logging_config import setup_logging
    saved = logging.root.handlers[:]
    had_gate = os.environ.pop("LOG_SYSLOG_ENABLED", None)
    try:
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        monkeypatch.setattr(app_config_mod.config, "LOG_SERVER_HOST", "192.168.68.102", raising=False)
        monkeypatch.setattr(app_config_mod.config, "LOG_SERVER_PORT", 514, raising=False)
        setup_logging()
        handlers = logging.root.handlers[:]
        assert any(isinstance(h, logging.handlers.SysLogHandler) for h in handlers)
    finally:
        if had_gate is not None:
            os.environ["LOG_SYSLOG_ENABLED"] = had_gate
        logging.root.handlers[:] = saved
