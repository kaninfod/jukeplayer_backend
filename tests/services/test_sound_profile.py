"""Sound profiles: the compiler + the apply chain (manager → live mpv)."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app, startup_event
from app.services.sound_profile import compile_snd_profile

PROFILE = {
    "preamp_db": "-3",
    "bands_db": {"63": "1.5", "125": "1", "16000": "-2.5"},
    "low_shelf_db": "",
    "high_shelf_db": "-1",
}

EXPECTED_AF = ("volume=-3dB,treble=f=8000:w=0.2:g=-1,"
               "equalizer=f=63:t=q:w=2:g=+1.5,equalizer=f=125:t=q:w=2:g=+1,"
               "equalizer=f=16000:t=q:w=2:g=-2.5")


def test_compiler_output_shape():
    af, errors = compile_snd_profile(PROFILE)
    assert errors == []
    assert af == EXPECTED_AF           # zero low-shelf skipped, bands low→high


def test_empty_profile_compiles_to_clear():
    af, errors = compile_snd_profile({})
    assert af == "" and errors == []


def test_compose_adds_and_autoderives_preamp():
    from app.services.sound_profile import compose_profiles
    base = {"preamp_db": -6.4, "bands_db": {"31": "-0.5", "63": "0.2", "125": "-2.4",
                                            "250": "-3.0", "500": "2.3", "1000": "5.0",
                                            "2000": "-4.9", "4000": "2.0",
                                            "8000": "0.5", "16000": "6.2"}}
    preset = {"bands_db": {"31": "-0.5", "2000": "1"}}
    composed, warnings = compose_profiles(base, preset)
    assert round(composed["bands_db"]["31"], 3) == -1.0        # the sums, band-wise
    assert round(composed["bands_db"]["2000"], 3) == -3.9
    assert round(composed["preamp_db"], 3) == min(-6.4, -5.0)  # the more negative
    assert warnings == []


def test_compose_clamps_with_warnings():
    from app.services.sound_profile import compose_profiles
    composed, warnings = compose_profiles({"bands_db": {"63": "10"}},
                                          {"bands_db": {"63": "10"}})
    assert composed["bands_db"]["63"] == 12.0
    assert any("clamped" in w for w in warnings)


def test_compose_without_preset_autoderives_preamp():
    from app.services.sound_profile import compose_profiles
    composed, _ = compose_profiles({"bands_db": {"63": "8"}}, None)
    assert composed["preamp_db"] == -8.0


def test_range_and_bandname_validation():
    bad = {"preamp_db": "5", "bands_db": {"1600": "2", "63": "99"}}
    af, errors = compile_snd_profile(bad)
    assert af == ""
    assert any("preamp" in e for e in errors)
    assert any("unknown band" in e for e in errors)
    assert any("63" in e for e in errors)


def test_zero_bands_left_out():
    ten = {b: "0" for b in ("31", "63", "125", "250", "500", "1000",
                            "2000", "4000", "8000", "16000")}
    assert compile_snd_profile({"bands_db": ten}) == ("", [])


# --- the apply chain -------------------------------------------------------------

class FakeMpv:
    def __init__(self):
        self.af = ""


def _inject_speaker(speakers_service, store, name="test_bt", backend_name="mpv"):
    """A registry speaker whose mpv backend exists in stub form (no real
    mpv spawn — __new__ skips the constructor, the fake player records the
    'af' property sets)."""
    from app.playback_backends.mpv import MPVService
    from app.services.speakers_service import Speaker
    backend = MPVService.__new__(MPVService)
    backend.device_name = name
    backend.player = FakeMpv()
    player = SimpleNamespace(playback_backend=backend, device_name=name, stop=None,
                             get_context=lambda minimal=False: {"status": "stop"})
    speaker = Speaker("sp-1", name, backend_name, player)
    speakers_service._speakers[name] = speaker
    store.add_speaker(name, backend=backend_name)
    return speaker


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def initialized_app(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.config.CONFIG_FILE", str(tmp_path / "config.json"))
    await startup_event()   # builds the service container (empty store in tmp)


def _services():
    from app.core.service_container import get_service
    return (get_service("config_store"), get_service("speakers_service"),
            get_service("speaker_manager"))


@pytest.mark.asyncio
async def test_set_sound_profile_persists_and_hot_sets(initialized_app):
    store, speakers_service, manager = _services()
    speaker = _inject_speaker(speakers_service, store)

    result = await manager.set_sound_profile("test_bt", PROFILE)
    assert result["ok"] is True
    # the calibration alone composes to itself (no preset): the auto-preamp
    # rule = min(-3, -(max boost)) = min(-3, -1.5) = -3
    assert result["af"] == EXPECTED_AF
    backend = speaker.mediaplayer.playback_backend
    assert backend.player.af == EXPECTED_AF   # the live mpv got the chain

    persisted = store.section("speakers")[0]
    assert persisted["options"]["room_correction"]["bands_db"]["63"] == "1.5"
    assert "sound_profile" not in persisted["options"]   # the legacy key cleaned


@pytest.mark.asyncio
async def test_empty_profile_removes_the_option(initialized_app):
    store, speakers_service, manager = _services()
    _inject_speaker(speakers_service, store)
    empty = {"preamp_db": "", "bands_db": {}, "low_shelf_db": "", "high_shelf_db": ""}
    result = await manager.set_sound_profile("test_bt", empty)
    assert result["ok"] is True and result["af"] == ""
    opts = store.section("speakers")[0]["options"]
    assert "room_correction" not in opts
    assert "sound_profile" not in opts


@pytest.mark.asyncio
async def test_set_sound_profile_refuses_chromecast(initialized_app):
    store, speakers_service, manager = _services()
    from app.services.speakers_service import Speaker
    store.add_speaker("cast", backend="chromecast")
    speakers_service._speakers["cast"] = Speaker(
        "sp-2", "cast", "chromecast",
        SimpleNamespace(playback_backend=SimpleNamespace(),
                        get_context=lambda minimal=False: {"status": "stop"}))
    with pytest.raises(ValueError):
        await manager.set_sound_profile("cast", PROFILE)


@pytest.mark.asyncio
async def test_config_page_renders_static_dialog_with_prefills(initialized_app):
    store, speakers_service, manager = _services()
    speaker = _inject_speaker(speakers_service, store)
    await manager.set_sound_profile("test_bt", PROFILE)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get("/kiosk/config")
        assert page.status_code == 200
        html = page.text
        # the per-row dialog with a STATIC rendered hx-post (never dynamic)
        assert 'hx-post="/kiosk/config/speakers/test_bt/sound-profile"' in html
        assert "sound-profile-dialog" in html
        assert 'step="any"' in html                      # AutoEQ decimals enter as-is
        # the current profile prefills the fields server-side
        assert 'name="band_63"' in html and 'value="1.5"' in html
        assert 'value="-3"' in html                      # the preamp's stored value


@pytest.mark.asyncio
async def test_sound_profile_route_toasts(initialized_app):
    from app.core.service_container import get_service
    store, speakers_service, manager = _services()
    _inject_speaker(speakers_service, store)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/kiosk/config/speakers/test_bt/sound-profile",
            data={"preamp_db": "-3", "band_63": "1.5", "high_shelf_db": "-1",
                  **{"band_" + b: "" for b in ("31", "125", "250", "500", "1000",
                                               "2000", "4000", "8000", "16000")}})
        assert resp.status_code == 200
        assert "Room correction applied to 'test_bt'" in resp.headers["HX-Trigger"]
        # out-of-range → the error toast, nothing persisted
        bad = await client.post(
            "/kiosk/config/speakers/test_bt/sound-profile",
            data={"band_63": "99"})
        trigger = bad.headers["HX-Trigger"]
        assert "error" in trigger
        entry = store.section("speakers")[0]
        # the out-of-range apply changed nothing: the first apply's profile is intact
        assert entry["options"]["room_correction"]["bands_db"]["63"] == "1.5"


@pytest.mark.asyncio
async def test_dsp_setting_bypass_and_preset(initialized_app):
    store, speakers_service, manager = _services()
    speaker = _inject_speaker(speakers_service, store)
    await manager.set_sound_profile("test_bt", PROFILE)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # DSP on + a preset → the composed chain lands (vocal bumps 1k +2)
        resp = await client.post("/kiosk/devices/sound-setting",
            data={"name": "test_bt", "dsp_enabled": "on", "preset": "vocal"})
        assert resp.status_code == 200
        assert "Preset 'vocal' applied" in resp.headers["HX-Trigger"]
        af = speaker.mediaplayer.playback_backend.player.af
        assert "equalizer=f=1000:t=q:w=2:g=+2" in af           # the base's +0 + vocal's +2
        # the bypass: unchecked checkbox = dsp_enabled missing from the form
        resp = await client.post("/kiosk/devices/sound-setting", data={"name": "test_bt"})
        assert "bypassed" in resp.headers["HX-Trigger"]
        assert speaker.mediaplayer.playback_backend.player.af == ""
        # ...but the preset choice SURVIVES the bypass (the select was disabled/not posted)
        assert store.section("speakers")[0]["options"]["sound_preset"] == "vocal"
        assert store.section("speakers")[0]["options"]["dsp_enabled"] is False

        # the devices page renders the dialog with the state
        page = await client.get("/kiosk/devices", headers={"HX-Request": "true"})
        assert "/kiosk/devices/sound-setting" in page.text
        assert "Use DSP" in page.text