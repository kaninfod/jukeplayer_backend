"""Tests for the JSON config store + merged effective-config view."""
import json
import os
import stat

import pytest

from app.services.config_store import (
    ConfigService,
    ConfigStoreService,
    SCHEMA_VERSION,
    SECTION_DEFAULTS,
    mpv_config_view,
    SubsonicConfigAdapter,
)


@pytest.fixture
def store(tmp_path):
    return ConfigStoreService(path=str(tmp_path / "config.json"))


@pytest.fixture
def config_service(store, monkeypatch):
    system = type("SysCfg", (), {"HTTP_REQUEST_TIMEOUT": 10, "LOG_SERVER_HOST": "x", "LOG_SERVER_PORT": 514})()
    return ConfigService(store=store, system_config=system)


def test_store_starts_with_schema_defaults(store):
    assert store.data["version"] == SCHEMA_VERSION
    for section in ("subsonic", "mpv", "logging", "server", "chromecast"):
        assert section in store.data
    assert store.data["speakers"] == []


def test_update_section_persists_atomically(store, tmp_path):
    store.update_section("subsonic", {"url": "http://gonic:80", "bogus_key": "dropped"})

    store2 = ConfigStoreService(path=store.path)
    assert store2.data["subsonic"]["url"] == "http://gonic:80"
    assert "bogus_key" not in store2.data["subsonic"]

    mode = stat.S_IMODE(os.stat(store.path).st_mode)
    assert mode == 0o600


def test_secret_is_not_overwritten_by_blank(store):
    store.update_section("subsonic", {"password": "first-pass"})
    store.update_section("subsonic", {"password": ""})  # blank must keep existing
    assert store.data["subsonic"]["password"] == "first-pass"


def test_set_speakers_normalizes(store):
    store.set_speakers([
        {"name": "LIVING_ROOM", "backend": "chromecast", "is_default": True},
        {"name": "boom3", "backend": "mpv", "options": {"device_name": "BOOM3"}},
        "garbage-entry",
    ])
    names = [s["name"] for s in store.data["speakers"]]
    assert names == ["living_room", "boom3"]
    assert store.data["speakers"][0]["is_default"] is True


def test_effective_view_masks_secrets(config_service, store):
    store.update_section("subsonic", {"password": "hunter2"})
    view = config_service.effective()
    pw = view["sections"]["subsonic"]["keys"]["password"]
    assert pw["masked"] is True and pw["set"] is True and pw["value"] == ""
    url = view["sections"]["subsonic"]["keys"]["url"]
    assert url["source"] in ("store", "default")


def test_apply_runtime_sets_live_log_level(config_service):
    import logging
    store = config_service.store
    store.update_section("logging", {"level": "WARNING"})
    applied = config_service.apply_runtime()
    assert applied == {"logging": "live"}
    assert logging.getLogger().level == logging.WARNING
    logging.getLogger().setLevel(logging.INFO)  # restore for other tests


def test_default_speaker_flag(config_service, store):
    store.set_speakers([
        {"name": "living_room", "backend": "chromecast", "is_default": True},
        {"name": "kitchen", "backend": "chromecast"},
    ])
    assert config_service.default_speaker_name() == "living_room"


def test_mpv_view_per_speaker_socket(config_service, store):
    store.set_speakers([{"name": "boom3", "backend": "mpv", "options": {"device_name": "BOOM3"}}])
    view = mpv_config_view(config_service, "boom3", {"device_name": "BOOM3"})
    assert view.MPV_DEVICE_NAME == "BOOM3"
    assert view.MPV_IPC_SOCKET == "/tmp/jukebox-mpv-boom3.sock"
    # per-speaker socket, distinct from any other MPV speaker
    other = mpv_config_view(config_service, "boom4", {})
    assert other.MPV_IPC_SOCKET != view.MPV_IPC_SOCKET


def test_subsonic_adapter_maps_store_values(config_service, store):
    store.update_section("subsonic", {"url": "http://gonic:80", "user": "u", "password": "p"})
    adapter = SubsonicConfigAdapter(config_service)
    assert adapter.SUBSONIC_URL == "http://gonic:80"
    assert adapter.SUBSONIC_USER == "u"
    assert adapter.SUBSONIC_PASS == "p"
    assert adapter.HTTP_REQUEST_TIMEOUT == config_service.system.HTTP_REQUEST_TIMEOUT