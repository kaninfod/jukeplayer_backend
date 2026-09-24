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

# New unified routes


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

