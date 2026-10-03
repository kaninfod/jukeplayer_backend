import json
import asyncio
from datetime import datetime

from fastapi import APIRouter, Request, Query, HTTPException, Body
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.config import config
from app.core.service_container import get_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/web/templates")


def _with_toast(response, message: str, theme: str = "success"):
    """Attach an HX-Trigger header so the client flashes a toast notification
    after the htmx swap (listener lives in static/js/kiosk-toast.js)."""
    response.headers["HX-Trigger"] = json.dumps({"kioskToast": {"message": message, "theme": theme}})
    return response


def format_iso_string(date_str: str, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not date_str:
        return ""
    try:
        return datetime.fromisoformat(date_str).strftime(fmt)
    except (ValueError, TypeError):
        # Fallback if the string isn't valid ISO format
        return date_str

# 3. Register the filter into the Jinja2 Environment
templates.env.filters["datetimeformat"] = format_iso_string


def config_get(config, dotted_path: str, fallback=""):
    """Resolve a dotted path in a client config dict; missing keys or
    intermediates return the fallback instead of raising (configs may be
    partial)."""
    value = config
    for key in dotted_path.split("."):
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return fallback
    return value

templates.env.filters["config_get"] = config_get

GROUP_RANGES = {
    'A-C': ['A', 'D'],
    'D-F': ['D', 'G'],
    'G-I': ['G', 'J'],
    'J-L': ['J', 'M'],
    'M-O': ['M', 'P'],
    'P-R': ['P', 'S'],
    'S-U': ['S', 'V'],
    'V-X': ['V', 'Y'],
    'Y-Z': ['Y', '[']  # '[' = the sentinel after Z, so Z artists are included
}


def _filter_artists_by_group(group_name: str, artists: list) -> list:
    group_range = GROUP_RANGES.get(group_name)
    if not group_range:
        return []

    filtered_artists = []
    for artist in artists:
        name = artist.get('name') if isinstance(artist, dict) else getattr(artist, 'name', '')
        if not name:
            continue
        first = name.upper()[0]
        if first >= group_range[0] and first < group_range[1]:
            filtered_artists.append(artist)
    return filtered_artists


def _is_htmx_request(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"

# Configuration UI (Phase A)

def _config_ui_context(saved_section: str | None = None) -> dict:
    """Template-friendly view: plain scalar values per key + flags."""
    from app.core.service_container import get_service
    config_service = get_service("config_service")

    def scalars(section: str) -> dict:
        return {key: entry["value"] for key, entry in config_service.effective()["sections"][section]["keys"].items()}

    subsonic = scalars("subsonic")
    context = {
        "config": {
            "subsonic": {**subsonic, "password_set": bool(config_service.subsonic().get("password"))},
            "logging": scalars("logging"),
            "server": scalars("server"),
        },
        **_speakers_card_context(),
        "system_env": {key: entry["value"] for key, entry in config_service.effective()["sections"]["system_env"]["keys"].items()},
        "saved_section": saved_section,
        "applies": "live" if saved_section == "logging" else "restart" if saved_section else None,
    }
    return context


@router.get("/kiosk/config", response_class=HTMLResponse)
async def kiosk_config_page(request: Request):
    context = _config_ui_context()
    if _is_htmx_request(request):
        return templates.TemplateResponse(request=request,
            name="components/kiosk/config/_config.html", context=context)
    return templates.TemplateResponse(request=request,
        name="pages/kiosk/config.html", context=context)


@router.post("/kiosk/config/save/{section}")
async def kiosk_config_save(section: str, request: Request):
    from app.core.service_container import get_service
    from app.services.config_store import VALID_LOG_LEVELS

    form = await request.form()
    store = get_service("config_store")
    config_service = get_service("config_service")

    try:
        if section == "subsonic":
            values = {key: (form.get(key) or "") for key in
                      ("url", "user", "client", "api_version")}
            if form.get("password"):
                values["password"] = form.get("password")
            store.update_section("subsonic", values)
        elif section == "logging":
            level = str(form.get("level", "")).upper()
            if level not in VALID_LOG_LEVELS:
                return HTMLResponse(f"Invalid log level: {level}", status_code=400)
            store.update_section("logging", {"level": level})
            config_service.apply_runtime()
        elif section == "server":
            store.update_section("server", {
                "cors_allow_origins": form.get("cors_allow_origins", ""),
                "public_base_url": form.get("public_base_url", ""),
            })
        else:
            return HTMLResponse(f"Unknown section: {section}", status_code=404)
    except ValueError as e:
        return HTMLResponse(str(e), status_code=400)

    context = _config_ui_context(saved_section=section)
    context["request"] = request
    return templates.TemplateResponse(request=request,
        name="components/kiosk/config/_config.html", context=context)


# Speakers card (Phase B): every action re-renders the card fragment.

def _speakers_card_context(message: str | None = None, error: str | None = None) -> dict:
    """Unified speaker list (Chromecast + Bluetooth + local) — store entries
    merged with the runtime flags from the Speaker registry."""
    manager = get_service("speaker_manager")
    speakers_service = get_service("speakers_service")
    default_name = None
    try:
        default_name = get_service("config_service").default_speaker_name()
    except Exception:
        pass
    speakers = []
    for entry in manager.configured():
        speaker = speakers_service.get_speaker(speaker_name=entry["name"])
        speakers.append({
            "name": entry["name"],
            "display_name": entry.get("display_name") or "",
            "is_default": entry.get("is_default", False),
            "speaker_type": getattr(speaker, "type", "local") if speaker else "local",
            "icon": getattr(speaker, "icon", None) if speaker else None,
            "bt_mac": getattr(speaker, "bt_mac", None) if speaker else None,
            "cc_host": getattr(speaker, "cc_host", None) if speaker else None,
            "address": (getattr(speaker, "bt_mac", None) if speaker else None)
                       or (getattr(speaker, "cc_host", None) if speaker else None),
        })
    from app.services.speaker_manager_service import SPEAKER_ICONS
    return {
        "speakers": speakers,
        "default_name": default_name,
        "speaker_icons": SPEAKER_ICONS,
        "message": message,
        "error": error,
    }


def _bt_service_or_none():
    """The bluetooth service may be unavailable (host without BT tools) —
    the cards degrade gracefully instead of failing."""
    try:
        return get_service("bluetooth_service")
    except Exception:
        return None


def _render_speakers_card(request: Request, **ctx):
    return templates.TemplateResponse(request=request,
        name="components/kiosk/config/_speakers_card.html", context=ctx)


# --- Connect-a-new-speaker card (kiosk/system) --------------------------------
# One card, two flows: Chromecast (scan → add) and Bluetooth (pairing-mode
# scan → pair = pair+trust+connect+add-as-speaker). Managed speakers are
# hidden from both lists with a names note.

@router.post("/kiosk/system/refresh-subsonic")
async def kiosk_refresh_subsonic():
    """The config's "Refresh subsonic data" button: re-runs the cached artist
    metadata (counts/genres) so new gonic albums show without a restart."""
    try:
        svc = get_service("artist_metadata_service")
        summary = await asyncio.to_thread(svc.refresh)
    except KeyError:
        message, theme = "Metadata service not initialized — restart the server first", "error"
    except Exception as e:
        message, theme = f"Refresh failed: {e}", "error"
    else:
        message, theme = f"Refreshed: {summary['artists']} artists, {summary['genres']} genres", "success"
    # Always 200: htmx ignores response headers on error statuses, so a 500
    # here would swallow the toast and leave the kiosk button silently dead.
    return _with_toast(HTMLResponse(""), message, theme=theme)

def _connect_card_context(message: str | None = None, error: str | None = None,
                          cc_devices=None, cc_scanned: bool = False,
                          bt_devices=None, bt_scanned: bool = False) -> dict:
    bt = _bt_service_or_none()
    manager = get_service("speaker_manager")

    cc_list = []
    if cc_devices is not None:
        for d in cc_devices:
            cc_list.append({**d, "managed": bool(d.get("configured"))})
    bt_list = []
    if bt_devices is not None:
        managed_macs = set()
        from app.services.bluetooth_service import mac_from_sink_id
        for s in manager.configured():
            mac = mac_from_sink_id((s.get("options") or {}).get("audio_device"))
            if mac:
                managed_macs.add(mac)
        for d in bt_devices:
            entry = {**d, "managed": d.get("mac") in managed_macs}
            name = (d.get("name") or "").strip()
            # managed devices stay VISIBLE (with a Managed pill) instead of
            # being hidden behind a note — user preference, 2026-09-26
            if entry["managed"] or d.get("paired") or d.get("connected") or d.get("audio") or (name and name != d["mac"]):
                bt_list.append(entry)

    return {
        "cc_devices": cc_list,
        "cc_scanned": cc_scanned,
        "bt_devices": bt_list,
        "bt_scanned": bt_scanned,
        "message": message,
        "error": error,
    }


def _render_connect_card(request: Request, **ctx):
    return templates.TemplateResponse(request=request,
        name="components/kiosk/config/_connect_speaker_card.html", context=ctx)


@router.get("/kiosk/system/connect", response_class=HTMLResponse)
async def kiosk_connect_page(request: Request):
    """The Connect Speaker page (linked from the System menu). The card's
    scan/pair buttons re-render the card in place (htmx swaps)."""
    if _is_htmx_request(request):
        return _render_connect_card(request, **_connect_card_context())
    return templates.TemplateResponse(request=request,
        name="pages/kiosk/system_connect.html", context={"request": request, "config": config, "kiosk_mode": True})


@router.get("/kiosk/system/connect/scan/cc")
async def kiosk_connect_scan_cc(request: Request):
    manager = get_service("speaker_manager")
    try:
        devices = await asyncio.to_thread(manager.discover)
        resp = _render_connect_card(request, **_connect_card_context(
            cc_devices=devices, cc_scanned=True))
        return _with_toast(resp, f"Chromecast scan finished — {len(devices)} device{'s' if len(devices) != 1 else ''} found")
    except Exception as e:
        logger.warning(f"CC scan failed: {e}")
        resp = _render_connect_card(request, **_connect_card_context(
            error=f"Chromecast scan failed: {e}", cc_scanned=True))
        return _with_toast(resp, f"Chromecast scan failed: {e}", theme="error")


@router.get("/kiosk/system/connect/scan/bt")
async def kiosk_connect_scan_bt(request: Request):
    bt = _bt_service_or_none()
    if bt is None:
        resp = _render_connect_card(request, **_connect_card_context(
            error="Bluetooth tools unavailable", bt_scanned=True))
        return _with_toast(resp, "Bluetooth tools unavailable", theme="error")
    try:
        devices = await asyncio.to_thread(bt.scan)
        resp = _render_connect_card(request, **_connect_card_context(
            bt_devices=devices, bt_scanned=True))
        return _with_toast(resp, f"Bluetooth scan finished — {len(devices)} device{'s' if len(devices) != 1 else ''} found")
    except Exception as e:
        logger.warning(f"BT scan failed: {e}")
        resp = _render_connect_card(request, **_connect_card_context(
            error=f"Bluetooth scan failed: {e}", bt_scanned=True))
        return _with_toast(resp, f"Bluetooth scan failed: {e}", theme="error")


@router.post("/kiosk/system/connect/add-cc")
async def kiosk_connect_add_cc(request: Request):
    form = await request.form()
    manager = get_service("speaker_manager")
    try:
        # store the discovered cast UUID so connect() matches robustly even
        # when the friendly name's case/spacing doesn't (cast groups!)
        cast_uuid = str(form.get("uuid") or "").strip()
        options = {"cast_uuid": cast_uuid} if cast_uuid else {}
        entry = manager.add_speaker(name=str(form.get("name") or ""), backend="chromecast",
                                    options=options)
        resp = _render_connect_card(request, **_connect_card_context(
            message=f"Speaker added: {entry.get('display_name') or entry['name']}"))
        return _with_toast(resp, f"Speaker added: {entry.get('display_name') or entry['name']}")
    except ValueError as e:
        resp = _render_connect_card(request, **_connect_card_context(error=str(e)))
        return _with_toast(resp, str(e), theme="error")


@router.post("/kiosk/system/connect/pair")
async def kiosk_connect_pair(request: Request):
    form = await request.form()
    bt = _bt_service_or_none()
    if bt is None:
        resp = _render_connect_card(request, **_connect_card_context(error="Bluetooth tools unavailable"))
        return _with_toast(resp, "Bluetooth tools unavailable", theme="error")
    mac = str(form.get("mac") or "")
    manager = get_service("speaker_manager")
    try:
        result = await asyncio.to_thread(bt.pair_and_connect, mac)
        if result.get("error"):
            resp = _render_connect_card(request, **_connect_card_context(
                error=result["error"], bt_scanned=True, bt_devices=await asyncio.to_thread(bt.scan)))
            return _with_toast(resp, result["error"], theme="error")
        # pairing implies the speaker is wanted — add it automatically
        info = await asyncio.to_thread(bt.info, mac)
        device_name = info.get("name") or mac.replace(":", "_").lower()
        message = f"Paired and connected: {result.get('name') or mac}"
        sink = await asyncio.to_thread(bt.sink_for_device, mac)
        if sink:
            try:
                entry = manager.add_speaker(name=device_name, backend="mpv",
                                            options={"audio_device": sink},
                                            display_name=device_name)
                message += f" — added as speaker: {entry.get('display_name') or entry['name']}"
                speaker_obj = get_service("speakers_service").get_speaker(speaker_name=entry["name"])
                if speaker_obj:
                    speaker_obj.available = True
                    speaker_obj.connected = True   # pair_and_connect left the link up
                    speaker_obj.battery = bt.battery_percent(mac, info.get("uuids"))
            except ValueError:
                pass  # already configured
        resp = _render_connect_card(request, **_connect_card_context(
            message=message, bt_scanned=True, bt_devices=await asyncio.to_thread(bt.scan)))
        return _with_toast(resp, message)
    except Exception as e:
        logger.warning(f"Pairing failed: {e}")
        resp = _render_connect_card(request, **_connect_card_context(
            error=f"Pairing failed: {e}", bt_scanned=True))
        return _with_toast(resp, f"Pairing failed: {e}", theme="error")


@router.post("/kiosk/system/connect/manual")
async def kiosk_connect_manual(request: Request):
    form = await request.form()
    manager = get_service("speaker_manager")
    try:
        entry = manager.add_speaker(
            name=str(form.get("name") or ""),
            backend=str(form.get("backend") or "chromecast"),
            options={"audio_device": str(form.get("audio_device") or "")} if form.get("backend") == "mpv" else {},
            display_name=str(form.get("display_name") or "") or None,
        )
        resp = _render_connect_card(request, **_connect_card_context(
            message=f"Speaker added: {entry.get('display_name') or entry['name']}"))
        return _with_toast(resp, f"Speaker added: {entry.get('display_name') or entry['name']}")
    except ValueError as e:
        resp = _render_connect_card(request, **_connect_card_context(error=str(e)))
        return _with_toast(resp, str(e), theme="error")


@router.post("/kiosk/config/speakers/{name}/display")

@router.post("/kiosk/config/speakers/{name}/display")
async def kiosk_speakers_display(name: str, request: Request):
    """htmx sends the hx-prompt value as the HX-Prompt header; a form field
    works as fallback."""
    form = await request.form()
    display = request.headers.get("HX-Prompt") or str(form.get("display_name") or "")
    manager = get_service("speaker_manager")
    try:
        result = manager.set_display_name(name, display)
        label = result["display_name"] or name
        resp = _render_speakers_card(request, **_speakers_card_context(
            message=f"Display name for {name}: {label}"))
        return _with_toast(resp, f"Display name for {name}: {label}")
    except ValueError as e:
        resp = _render_speakers_card(request, **_speakers_card_context(error=str(e)))
        return _with_toast(resp, str(e), theme="error")


@router.post("/kiosk/config/speakers/{name}/remove")
async def kiosk_speakers_remove(name: str, request: Request):
    manager = get_service("speaker_manager")
    try:
        await manager.remove_speaker(name)
        resp = _render_speakers_card(request, **_speakers_card_context(
            message=f"Removed {name}"))
        return _with_toast(resp, f"Removed {name}")
    except ValueError as e:
        resp = _render_speakers_card(request, **_speakers_card_context(error=str(e)))
        return _with_toast(resp, str(e), theme="error")


@router.post("/kiosk/config/speakers/{name}/default")
async def kiosk_speakers_default(name: str, request: Request):
    manager = get_service("speaker_manager")
    try:
        manager.set_default(name)
        resp = _render_speakers_card(request, **_speakers_card_context(
            message=f"Default speaker: {name}"))
        return _with_toast(resp, f"Default speaker: {name}")
    except ValueError as e:
        resp = _render_speakers_card(request, **_speakers_card_context(error=str(e)))
        return _with_toast(resp, str(e), theme="error")


@router.post("/kiosk/config/speakers/{name}/icon")
async def kiosk_speakers_icon(name: str, request: Request):
    """Per-row glyph dropdown (config table): set the speaker's mdi icon."""
    form = await request.form()
    icon = str(form.get("icon") or "").strip()
    manager = get_service("speaker_manager")
    try:
        result = manager.set_speaker_icon(name, icon)
        resp = _render_speakers_card(request, **_speakers_card_context(
            message=f"Icon for {name}: {result['icon']}"))
        return _with_toast(resp, f"Icon for {name}: {result['icon']}")
    except ValueError as e:
        resp = _render_speakers_card(request, **_speakers_card_context(error=str(e)))
        return _with_toast(resp, str(e), theme="error")


@router.post("/kiosk/config/speakers/default")
async def kiosk_speakers_default_dropdown(request: Request):
    """Default-speaker dropdown under the table (replaces the star column)."""
    form = await request.form()
    name = str(form.get("name") or "").strip()
    manager = get_service("speaker_manager")
    try:
        manager.set_default(name)
        resp = _render_speakers_card(request, **_speakers_card_context(
            message=f"Default speaker: {name}"))
        return _with_toast(resp, f"Default speaker: {name}")
    except ValueError as e:
        resp = _render_speakers_card(request, **_speakers_card_context(error=str(e)))
        return _with_toast(resp, str(e), theme="error")


# Bluetooth card (Phase C): scan/pair/connect for BT speakers + "add as
# speaker" wiring through the SpeakerManager (mpv backend + pulse sink).

def _managed_speaker_macs() -> set:
    """MACs of BT devices that already have a speaker entry in the store —
    they are managed from the Speakers card, not the Bluetooth card."""
    from app.services.bluetooth_service import mac_from_sink_id
    macs = set()
    try:
        manager = get_service("speaker_manager")
        for speaker in manager.configured():
            mac = mac_from_sink_id((speaker.get("options") or {}).get("audio_device"))
            if mac:
                macs.add(mac)
    except Exception as e:
        logger.debug(f"Could not read managed speaker MACs: {e}")
    return macs


def _bluetooth_card_context(message: str | None = None, error: str | None = None,
                            scanned: bool = False, devices: list | None = None) -> dict:
    bt = _bt_service_or_none()
    if bt is None:
        return {"powered": None, "controller": None, "devices": [], "scanned": scanned,
                "message": message, "error": error or "Bluetooth tools unavailable (bluetoothctl)",
                "managed_devices": 0, "hidden_devices": 0}
    context = {**bt.status(),
               "devices": devices if devices is not None else bt.devices(),
               "scanned": scanned, "message": message, "error": error}
    managed = _managed_speaker_macs()
    managed_names = []
    sinks = {s["name"] for s in bt.bluez_sinks()}
    devices = []
    hidden = 0
    managed_count = 0
    for device in context["devices"]:
        mac = device["mac"]
        # devices with a speaker entry live in the Speakers card — hide here
        if mac in managed:
            managed_names.append(device.get("name") or mac)
            managed_count += 1
            continue
        wanted = f"bluez_sink.{mac.replace(':', '_')}."
        device["sink"] = next((s for s in sinks if s.startswith(wanted)), None)
        # keep paired/connected + audio devices visible; named unknowns too
        # (their class may not have come through in the scan window); hide
        # unpaired non-audio devices that never announced a name (beacons).
        name = (device.get("name") or "").strip()
        if device.get("paired") or device.get("connected") or device.get("audio") \
                or (name and name != mac):
            devices.append(device)
        else:
            hidden += 1
    devices.sort(key=lambda d: (not d.get("connected"), not d.get("paired"),
                                not d.get("audio"),
                                (d.get("name") or d["mac"]).lower()))
    context["devices"] = devices
    context["hidden_devices"] = hidden
    context["managed_devices"] = managed_count
    context["managed_names"] = managed_names
    return context


def _render_bluetooth_card(request: Request, **ctx):
    return templates.TemplateResponse(request=request,
        name="components/kiosk/config/_bluetooth_card.html", context=ctx)


@router.post("/kiosk/devices/bt-toggle")
async def kiosk_devices_bt_toggle(payload: dict = Body(...)):
    """Connect/disconnect a BT-backed speaker's device (from the device card).
    Current state decides the action: sink present → disconnect, else connect."""
    name = str((payload or {}).get("name", "")).strip()
    manager = get_service("speaker_manager")
    speakers_service = get_service("speakers_service")
    speaker_obj = speakers_service.get_speaker(speaker_name=name)
    if not speaker_obj or speaker_obj.type != "bluetooth":
        raise HTTPException(status_code=400, detail=f"'{name}' is not a Bluetooth speaker")
    if speaker_obj.connected:
        result = await manager.disconnect_speaker(name)
    else:
        result = await manager.connect_speaker(name)
    return {"name": name, "connected": result["connected"]}


@router.get("/", response_class=HTMLResponse)
async def status_page(request: Request, kiosk: bool = False):
    return templates.TemplateResponse(request=request, name="pages/kiosk/player.html", context={
        "request": request,
        "kiosk_mode": True,
        "config": config
    })


@router.get("/kiosk/player", response_class=HTMLResponse)
async def kiosk_player_partial(request: Request):
    if _is_htmx_request(request):
        return templates.TemplateResponse(request=request, name="components/kiosk/_player_status.html", context={"request": request, "config": config},
        )
    return templates.TemplateResponse(request=request, name="pages/kiosk/player.html", context={"request": request, "config": config, "kiosk_mode": True},
    )


@router.get("/kiosk/menu-sheet", response_class=HTMLResponse)
async def kiosk_menu_sheet(request: Request):
    """The mobile menu sheet content: the speaker quick-select + the
    content links. Fetched by the menu sheet controller on open."""
    manager = get_service("speaker_manager")
    speakers = []
    for entry in manager.configured():
        speakers.append({
            "name": entry["name"],
            "display_name": entry.get("display_name") or "",
            "is_default": entry.get("is_default", False),
        })
    return templates.TemplateResponse(request=request,
        name="components/kiosk/shared/_menu_sheet.html",
        context={"request": request, "speakers": speakers})


@router.get("/kiosk/styleguide", response_class=HTMLResponse)
async def kiosk_styleguide(request: Request):
    """The living styleguide: renders the design system with its real
    classes so colors, pills and cards can be reviewed after theme
    changes. Static — no data dependencies."""
    if _is_htmx_request(request):
        return templates.TemplateResponse(request=request,
            name="components/kiosk/shared/_styleguide.html", context={"request": request})
    return templates.TemplateResponse(request=request,
        name="pages/kiosk/styleguide.html",
        context={"request": request, "kiosk_mode": True, "embed": request.query_params.get("embed")})


@router.get("/kiosk/devices", response_class=HTMLResponse)
async def kiosk_devices_partial(request: Request):
    from app.core.service_container import get_service
    context = {
        "request": request,
        "config": config,
    }
    
    speakers_service = get_service("speakers_service")
    context["speakers"] = speakers_service.to_dict()
    # BT runtime info now lives on the Speaker flags (updated by the state pass)
    try:
        context["fallback"] = get_service("config_service").default_speaker_name()
    except Exception:
        context["fallback"] = None
    logger.info(f"Rendering devices partial with speakers: {list(context['speakers'].keys())}")


    if _is_htmx_request(request):
        return templates.TemplateResponse(request=request, name="components/kiosk/device_selector/_devices_container.html", context=context)
    context["kiosk_mode"] = True
    return templates.TemplateResponse(request=request, name="pages/kiosk/devices.html", context=context)


@router.get("/kiosk/playlist", response_class=HTMLResponse)
async def kiosk_playlist_partial(request: Request, injected_client_id: str = Query(...)):
    speaker_broker_service = get_service("speaker_broker_service")
    speaker = speaker_broker_service.get_speaker_for_client(injected_client_id)

    player = speaker.mediaplayer if speaker else None
    playlist = player.playlist_manager.to_dict() if player and player.playlist_manager else []
    # pass the real current-track OBJECT so the template's compare works
    # (render-time highlight; a 0-based index has no .track_number)
    current_track = player.playlist_manager.current_track if player and player.playlist_manager else None
    context = {
        "request": request,
        "config": config,
        "playlist": playlist,
        "current_track": current_track,
    }

    if _is_htmx_request(request):
        return templates.TemplateResponse(request=request, name="components/kiosk/playlist/_playlist_view.html", context=context,
        )

    context["kiosk_mode"] = True
    return templates.TemplateResponse(request=request, name="pages/kiosk/playlist.html", context=context,
    )


@router.get("/kiosk/system", response_class=HTMLResponse)
async def kiosk_system_partial(request: Request):
    if _is_htmx_request(request):
        return templates.TemplateResponse(request=request, name="components/kiosk/_system_menu.html", context={"request": request, "config": config},
        )
    return templates.TemplateResponse(request=request, name="pages/kiosk/system.html", context={"request": request, "config": config, "kiosk_mode": True},
    )


@router.get("/kiosk/configure/{client_id}", response_class=HTMLResponse)
async def kiosk_configure(request: Request, client_id: str):
    from app.core.service_container import get_service
    ccs = get_service("control_clients_service")
    client = ccs.get_client(client_id)
    if not client:
        return HTMLResponse("Client not found", status_code=404)
    config = client.config or {}
    config_json = json.dumps(config, indent=2)
    if _is_htmx_request(request):
        return templates.TemplateResponse(request=request,
            name="components/kiosk/config_esp/_config_esp.html",
            context={"request": request, "client_id": client_id, "config_json": config_json,
                     "config": config, "client_name": client.user_name,
                     "refresh_splits": client.tft_refresh_splits or []})
    return templates.TemplateResponse(request=request,
        name="pages/kiosk/configure.html",
        context={"request": request, "client_id": client_id, "config_json": config_json,
                 "config": config, "client_name": client.user_name,
                 "refresh_splits": client.tft_refresh_splits or [], "kiosk_mode": True})


@router.post("/kiosk/configure/{client_id}/apply")
async def kiosk_configure_apply(request: Request, client_id: str):
    from app.core.service_container import get_service
    import asyncio
    ccs = get_service("control_clients_service")
    client = ccs.get_client(client_id)
    if not client or not client.send_callback:
        return HTMLResponse("Client not found or not connected", status_code=404)
    body = await request.json()
    await client.send_callback({"type": "config_set", "payload": {"config": body}})
    await asyncio.sleep(0.5)
    if request.query_params.get("reboot"):
        await client.send_callback({"type": "device_reset", "payload": {}})
    return HTMLResponse("Config sent" + (" — device rebooting" if request.query_params.get("reboot") else ""))


@router.get("/kiosk/clients", response_class=HTMLResponse)
async def kiosk_clients_partial(request: Request):
    import json
    from app.core.service_container import get_service

    ccs = get_service("control_clients_service")
    ss = get_service("speakers_service")
    client_info = ccs.to_dict()
    for client_id, client_data in client_info.items():
        speaker_name = client_data.get("speaker_name")
        speaker_info = ss.get_speaker(speaker_name=speaker_name).to_dict() if speaker_name else None
        client_data["speaker_info"] = speaker_info
        client_info[client_id] = client_data

    # control_clients_service = get_service("control_clients_service")
    # control_clients = control_clients_service.to_dict()
    
    if _is_htmx_request(request):
        
        return templates.TemplateResponse(request=request, name="components/kiosk/clients/_clients_container.html", context={"request": request, "clients": client_info},
        )
    
    return templates.TemplateResponse(request=request, name="pages/kiosk/clients.html", context={"request": request, "kiosk_mode": True, "clients": client_info})
    

@router.get("/kiosk/library", response_class=HTMLResponse)
async def kiosk_library_partial(
    request: Request,
    group: str | None = Query(None),
    artist_id: str | None = Query(None),
    artist_name: str | None = Query(None),
    search: str | None = Query(None),
):
    subsonic_service = get_service("subsonic_service")
    artist_metadata = get_service("artist_metadata_service")

    context = {
        "request": request,
        "config": config,
        "title": "Music Library",
        "content_template": "components/kiosk/media_library/_artist_directory.html",
        "back_url": None,
        "letter_groups": [],
        "genres": artist_metadata.genres(),
    }

    if search:
        # artist search: search3 with the album/song sections zeroed out
        artists = await asyncio.to_thread(subsonic_service.search_artists, search)
        context.update({
            "title": f"Artists matching “{search}”",
            "subtitle": f"{len(artists)} artist{'s' if len(artists) != 1 else ''} found",
            "content_template": "components/kiosk/media_library/_artists_container.html",
            "back_url": "/kiosk/library",
            "artists": artists,
            "search_query": search,
        })
        if _is_htmx_request(request):
            return templates.TemplateResponse(request=request, name="components/kiosk/media_library/_media_library.html", context=context)
        context["kiosk_mode"] = True
        return templates.TemplateResponse(request=request, name="pages/kiosk/library.html", context=context)

    if artist_id:
        albums = await asyncio.to_thread(subsonic_service.list_albums_for_artist, artist_id)
        context.update({
            "title": artist_name or "Albums",
            "content_template": "components/kiosk/media_library/_albums_container.html",
            "back_url": "/kiosk/library",
            "albums": albums or [],
            "artist": {"name": artist_name or "Unknown Artist"},
        })
        if _is_htmx_request(request):
            return templates.TemplateResponse(request=request, name="components/kiosk/media_library/_media_library.html", context=context)
        context["kiosk_mode"] = True
        return templates.TemplateResponse(request=request, name="pages/kiosk/library.html", context=context)

    # default: the artist directory — letter-grouped slim rows (genre chips
    # render their own row), driven by the cached metadata
    rows = []
    for artist in artist_metadata.artists():
        rows.append({
            "name": artist["name"],
            "dir_id": artist["dir_id"],
            "count": artist.get("count", 0),
            "genre": artist_metadata.genre_chip(artist["name"]),
        })
    rows.sort(key=lambda a: a["name"].upper())
    letter_groups = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        group = [a for a in rows if a["name"].upper().startswith(letter)]
        if group:
            letter_groups.append({"letter": letter, "rows": group, "count": len(group)})
    context["letter_groups"] = letter_groups

    if _is_htmx_request(request):
        return templates.TemplateResponse(request=request, name="components/kiosk/media_library/_media_library.html", context=context)
    context["kiosk_mode"] = True
    return templates.TemplateResponse(request=request, name="pages/kiosk/library.html", context=context)


@router.post("/kiosk/library/play/{album_id}", response_class=HTMLResponse)
async def kiosk_library_play_album(request: Request, album_id: str):
    playback_service = get_service("playback_service")
    ok = await playback_service.load_from_album_id(album_id)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Failed to load album {album_id}")

    if _is_htmx_request(request):
        return templates.TemplateResponse(request=request, name="components/kiosk/_player_status.html", context={"request": request, "config": config})
    return templates.TemplateResponse(request=request, name="pages/kiosk/player.html", context={"request": request, "config": config, "kiosk_mode": True},
    )


@router.get("/kiosk/nfc-client-select", response_class=HTMLResponse)
async def kiosk_nfc_client_select(
    request: Request,
    album_id: str = Query(...),
    album_name: str = Query(...)
):
    clients = {}
    try:
        control_clients_service = get_service("control_clients_service")
        clients = control_clients_service.get_all_clients(capability="nfc_reader")
        logger.info(f"Found {len(clients)} clients with NFC capability for album_id {album_id}: {[getattr(c, 'client_id', '?') for c in clients.values()]}")
    except Exception as e:
        logger.error(f"Failed to get clients: {e}")

    logger.info(f"Rendering NFC client select for album_id {album_id}")
    context = {
        "request": request,
        "config": config,
        "album_id": album_id,
        "album_name": album_name,
        "clients": clients,
    }
    if _is_htmx_request(request):
        return templates.TemplateResponse(request=request, name="components/kiosk/nfc_encoding/_nfc_client_select.html", context=context)
    context["kiosk_mode"] = True
    return templates.TemplateResponse(request=request, name="pages/kiosk/nfc.html", context=context)


@router.get("/kiosk/nfc", response_class=HTMLResponse)
async def kiosk_nfc_partial(
    request: Request,
    album_id: str = Query(...),
    album_name: str = Query(...),
    client_id: str = Query(None),
    client_name: str = Query(None),
    injected_client_id: str = Query(...)
):
    context = {
        "request": request,
        "album_id": album_id,
        "album_name": album_name,
        "client_id": client_id,
        "client_name": client_name,
        "initiating_client_id": injected_client_id
    }

    nfc_state = get_service("nfc_encoding_state")
    await nfc_state.start(album_id=album_id, album_name=album_name, client_id=client_id, client_name=client_name, initiating_client_id=injected_client_id)

    if _is_htmx_request(request):
        logger.info(f"Rendering NFC encoding partial for context {album_id} / {album_name} / client {client_id} / {client_name}")
        return templates.TemplateResponse(request=request, name="components/kiosk/nfc_encoding/_nfc_encoding.html", context=context)
    context["kiosk_mode"] = True
    return templates.TemplateResponse(request=request, name="pages/kiosk/nfc.html", context=context)

