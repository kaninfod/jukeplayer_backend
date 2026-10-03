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