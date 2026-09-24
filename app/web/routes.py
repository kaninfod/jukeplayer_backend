import json
import asyncio
from datetime import datetime

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.config import config
from app.core.service_container import get_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/web/templates")


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
    'A-D': ['A', 'E'],
    'E-H': ['E', 'I'],
    'I-L': ['I', 'M'],
    'M-P': ['M', 'Q'],
    'Q-T': ['Q', 'U'],
    'U-Z': ['U', '[']
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
        "speakers": config_service.speakers(),
        "system_env": {key: entry["value"] for key, entry in config_service.effective()["sections"]["system_env"]["keys"].items()},
        "saved_section": saved_section,
        "applies": "live" if saved_section == "logging" else "restart" if saved_section else None,
    }
    # the bluetooth card include needs its own context on the full page
    context.update(_bluetooth_card_context())
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
                      ("url", "user", "client", "api_version", "proxy_basic_user", "proxy_basic_pass")}
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

def _speakers_card_context(message: str | None = None, error: str | None = None,
                           discovered=None, scanned: bool = False) -> dict:
    from app.services.speaker_manager_service import normalize_speaker_name
    manager = get_service("speaker_manager")
    return {
        "speakers": manager.configured(),
        "discovered": discovered,
        "scanned": scanned,
        "message": message,
        "error": error,
    }


def _render_speakers_card(request: Request, **ctx):
    return templates.TemplateResponse(request=request,
        name="components/kiosk/config/_speakers_card.html", context=ctx)


@router.get("/kiosk/config/speakers/scan")
async def kiosk_speakers_scan(request: Request):
    manager = get_service("speaker_manager")
    try:
        devices = await asyncio.to_thread(manager.discover)
    except Exception as e:
        logger.warning(f"Speaker scan failed: {e}")
        return _render_speakers_card(request, **_speakers_card_context(
            error=f"Scan failed: {e}", scanned=True))
    return _render_speakers_card(request, **_speakers_card_context(discovered=devices, scanned=True))


@router.post("/kiosk/config/speakers/add")
async def kiosk_speakers_add(request: Request):
    form = await request.form()
    manager = get_service("speaker_manager")
    try:
        entry = manager.add_speaker(
            name=str(form.get("name") or ""),
            backend=str(form.get("backend") or "chromecast"),
            is_default=form.get("is_default") == "on",
            display_name=str(form.get("display_name") or ""),
        )
        return _render_speakers_card(request, **_speakers_card_context(
            message=f"Added {entry.get('display_name') or entry['name']}"))
    except ValueError as e:
        return _render_speakers_card(request, **_speakers_card_context(error=str(e)))


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
        return _render_speakers_card(request, **_speakers_card_context(
            message=f"Display name for {name}: {label}"))
    except ValueError as e:
        return _render_speakers_card(request, **_speakers_card_context(error=str(e)))


@router.post("/kiosk/config/speakers/{name}/remove")
async def kiosk_speakers_remove(name: str, request: Request):
    manager = get_service("speaker_manager")
    try:
        await manager.remove_speaker(name)
        return _render_speakers_card(request, **_speakers_card_context(
            message=f"Removed {name}"))
    except ValueError as e:
        return _render_speakers_card(request, **_speakers_card_context(error=str(e)))


@router.post("/kiosk/config/speakers/{name}/default")
async def kiosk_speakers_default(name: str, request: Request):
    manager = get_service("speaker_manager")
    try:
        manager.set_default(name)
        return _render_speakers_card(request, **_speakers_card_context(
            message=f"Default speaker: {name}"))
    except ValueError as e:
        return _render_speakers_card(request, **_speakers_card_context(error=str(e)))


# Bluetooth card (Phase C): scan/pair/connect for BT speakers + "add as
# speaker" wiring through the SpeakerManager (mpv backend + pulse sink).

def _bluetooth_card_context(message: str | None = None, error: str | None = None,
                            scanned: bool = False, devices: list | None = None) -> dict:
    bt = get_service("bluetooth_service")
    context = {**bt.status(),
               "devices": devices if devices is not None else bt.devices(),
               "scanned": scanned, "message": message, "error": error}
    sinks = {s["name"] for s in bt.bluez_sinks()}
    devices = []
    hidden = 0
    for device in context["devices"]:
        mac = device["mac"]
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
    return context


def _render_bluetooth_card(request: Request, **ctx):
    return templates.TemplateResponse(request=request,
        name="components/kiosk/config/_bluetooth_card.html", context=ctx)


@router.get("/kiosk/config/bluetooth/scan")
async def kiosk_bluetooth_scan(request: Request):
    bt = get_service("bluetooth_service")
    try:
        devices = await asyncio.to_thread(bt.scan)
        return _render_bluetooth_card(request, **_bluetooth_card_context(scanned=True, devices=devices))
    except Exception as e:
        logger.warning(f"Bluetooth scan failed: {e}")
        return _render_bluetooth_card(request, **_bluetooth_card_context(
            error=f"Scan failed: {e}", scanned=True))


@router.post("/kiosk/config/bluetooth/pair")
async def kiosk_bluetooth_pair(request: Request):
    form = await request.form()
    bt = get_service("bluetooth_service")
    mac = str(form.get("mac") or "")
    try:
        result = await asyncio.to_thread(bt.pair_and_connect, mac)
        if result.get("error"):
            return _render_bluetooth_card(request, **_bluetooth_card_context(
                error=result["error"], scanned=True,
                devices=await asyncio.to_thread(bt.scan)))
        return _render_bluetooth_card(request, **_bluetooth_card_context(
            message=f"Paired and connected: {result.get('name') or mac}", scanned=True,
            devices=await asyncio.to_thread(bt.scan)))
    except Exception as e:
        return _render_bluetooth_card(request, **_bluetooth_card_context(
            error=f"Pairing failed: {e}", scanned=True))


@router.post("/kiosk/config/bluetooth/connect")
async def kiosk_bluetooth_connect(request: Request):
    form = await request.form()
    bt = get_service("bluetooth_service")
    mac = str(form.get("mac") or "")
    try:
        result = await asyncio.to_thread(bt.connect, mac)
        if not result["connected"]:
            return _render_bluetooth_card(request, **_bluetooth_card_context(
                error=result.get("error") or "Connect failed"))
        return _render_bluetooth_card(request, **_bluetooth_card_context(
            message=f"Connected: {mac}"))
    except Exception as e:
        return _render_bluetooth_card(request, **_bluetooth_card_context(error=f"Connect failed: {e}"))


@router.post("/kiosk/config/bluetooth/disconnect")
async def kiosk_bluetooth_disconnect(request: Request):
    form = await request.form()
    bt = get_service("bluetooth_service")
    mac = str(form.get("mac") or "")
    await asyncio.to_thread(bt.disconnect, mac)
    return _render_bluetooth_card(request, **_bluetooth_card_context(message=f"Disconnected: {mac}"))


@router.post("/kiosk/config/bluetooth/forget")
async def kiosk_bluetooth_forget(request: Request):
    form = await request.form()
    bt = get_service("bluetooth_service")
    mac = str(form.get("mac") or "")
    await asyncio.to_thread(bt.forget, mac)
    return _render_bluetooth_card(request, **_bluetooth_card_context(message=f"Removed {mac}"))


@router.post("/kiosk/config/bluetooth/add-speaker")
async def kiosk_bluetooth_add_speaker(request: Request):
    """Create a speaker entry for a connected BT device: mpv backend +
    options.audio_device = its pulse sink (verified format)."""
    form = await request.form()
    bt = get_service("bluetooth_service")
    manager = get_service("speaker_manager")
    mac = str(form.get("mac") or "")
    try:
        info = await asyncio.to_thread(bt.info, mac)
        name = info.get("name") or mac.replace(":", "_").lower()
        sink = await asyncio.to_thread(bt.sink_for_device, mac)
        if not sink:
            return _render_bluetooth_card(request, **_bluetooth_card_context(
                error=f"{info.get('name') or mac} is not connected — no audio sink available yet"))
        entry = manager.add_speaker(
            name=name, backend="mpv",
            options={"audio_device": sink},
            display_name=str(form.get("display_name") or name),
        )
        return _render_bluetooth_card(request, **_bluetooth_card_context(
            message=f"Speaker added: {entry.get('display_name') or entry['name']} ({entry['name']})"))
    except ValueError as e:
        return _render_bluetooth_card(request, **_bluetooth_card_context(error=str(e)))
    except Exception as e:
        logger.warning(f"Add BT speaker failed: {e}")
        return _render_bluetooth_card(request, **_bluetooth_card_context(error=f"Could not add speaker: {e}"))


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


@router.get("/kiosk/devices", response_class=HTMLResponse)
async def kiosk_devices_partial(request: Request):
    from app.core.service_container import get_service
    context = {
        "request": request,
        "config": config,
    }
    
    speakers_service = get_service("speakers_service")
    context["speakers"] = speakers_service.to_dict()
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
    current_track_index = player.playlist_manager.current_index if player and player.playlist_manager else None
    context = {
        "request": request,
        "config": config,
        "playlist": playlist,
        "current_track": current_track_index,
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
            name="components/kiosk/configure/_configure.html",
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
):
    subsonic_service = get_service("subsonic_service")

    context = {
        "request": request,
        "config": config,
        "title": "Music Library",
        "content_template": "components/kiosk/media_library/_groups_container.html",
        "back_url": None,
        "groups": [{"name": name} for name in GROUP_RANGES.keys()],
    }

    if group and not artist_id:
        # Offloaded: blocking HTTP call, must not stall the event loop
        all_artists = await asyncio.to_thread(subsonic_service.list_artists)
        artists = _filter_artists_by_group(group, all_artists or [])
        context.update({
            "title": f"Music Library — {group}",
            "content_template": "components/kiosk/media_library/_artists_container.html",
            "back_url": "/kiosk/library",
            "artists": artists,
            "group": group,
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
            "back_url": f"/kiosk/library?group={group}" if group else "/kiosk/library",
            "albums": albums or [],
            "artist": {"name": artist_name or "Unknown Artist"},
            "group": group,
        })
        if _is_htmx_request(request):
            return templates.TemplateResponse(request=request, name="components/kiosk/media_library/_media_library.html", context=context)
        context["kiosk_mode"] = True
        return templates.TemplateResponse(request=request, name="pages/kiosk/library.html", context=context)

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

