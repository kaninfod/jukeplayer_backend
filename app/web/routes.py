from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.config import config
from app.core.service_container import get_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/web/templates")

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


async def _get_output_status_data() -> dict:
    from app.core.service_container import get_service
    from app.routes.output import _backend_key
    from app.playback_backends.factory import get_available_output_devices

    player = get_service("media_player_service")
    backend = getattr(player, "playback_backend", None)
    devices = get_available_output_devices()

    backend_status = await backend.get_status() if hasattr(backend, "get_status") else None
    readiness = (
        backend.get_output_readiness()
        if hasattr(backend, "get_output_readiness")
        else {"ready": True, "message": "No backend-specific checks"}
    )

    backend_name = _backend_key(backend)
    connected = readiness.get("ready", True)
    if backend_name == "chromecast" and hasattr(backend, "is_connected"):
        try:
            connected = bool(backend.is_connected())
        except Exception:
            connected = False

    for device in devices:
        if device.get("backend") == backend_name and device.get("device") == getattr(backend, "device_name", None):
            device["active"] = True
        else:
            device["active"] = False

        if device.get("backend") == "mpv":
            device["icon"] = "mdi-bluetooth-audio"
        elif device.get("backend") == "chromecast":
            device["icon"] = "mdi-cast"
        else:
            device["icon"] = "mdi-cast"

    return {
        "status": "ok",
        "active_backend": backend_name,
        "active_device": getattr(backend, "device_name", None),
        "connected": connected,
        "playback_backend_ready": readiness.get("ready", True),
        "backend_status": backend_status,
        "output_readiness": readiness,
        "capabilities": {
            "runtime_switch": True,
            "chromecast_device_selection": True,
            "bluetooth_via_mpv": True,
        },
        "devices": devices,
    }


def _is_htmx_request(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"

# New unified routes


@router.get("/", response_class=HTMLResponse)
async def status_page(request: Request, kiosk: bool = False):
    return templates.TemplateResponse("pages/kiosk/player.html", {
        "request": request,
        "kiosk_mode": True,
        "config": config
    })


@router.get("/kiosk/player", response_class=HTMLResponse)
async def kiosk_player_partial(request: Request):
    if _is_htmx_request(request):
        return templates.TemplateResponse(
            "components/kiosk/_player_status.html",
            {"request": request, "config": config},
        )
    return templates.TemplateResponse(
        "pages/kiosk/player.html",
        {"request": request, "config": config, "kiosk_mode": True},
    )


@router.get("/kiosk/devices", response_class=HTMLResponse)
async def kiosk_devices_partial(request: Request):
    context = {
        "request": request,
        "config": config,
        "status_data": await _get_output_status_data(),
    }
    if _is_htmx_request(request):
        return templates.TemplateResponse("components/kiosk/_device_selector.html", context)
    context["kiosk_mode"] = True
    return templates.TemplateResponse("pages/kiosk/devices.html", context)


@router.get("/kiosk/playlist", response_class=HTMLResponse)
async def kiosk_playlist_partial(request: Request):
    playback_service = get_service("playback_service")
    player = playback_service.player
    playlist_context = player.get_context() if player else {}
    context = {
        "request": request,
        "config": config,
        "playlist": playlist_context.get("playlist", []),
        "current_track": playlist_context.get("current_track"),
    }

    if _is_htmx_request(request):
        return templates.TemplateResponse(
            "components/kiosk/_playlist_view.html",
            context,
        )

    context["kiosk_mode"] = True
    return templates.TemplateResponse(
        "pages/kiosk/playlist.html",
        context,
    )


@router.get("/kiosk/system", response_class=HTMLResponse)
async def kiosk_system_partial(request: Request):
    if _is_htmx_request(request):
        return templates.TemplateResponse(
            "components/kiosk/_system_menu.html",
            {"request": request, "config": config},
        )
    return templates.TemplateResponse(
        "pages/kiosk/system.html",
        {"request": request, "config": config, "kiosk_mode": True},
    )


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
        all_artists = subsonic_service.list_artists()
        artists = _filter_artists_by_group(group, all_artists or [])
        context.update({
            "title": f"Music Library — {group}",
            "content_template": "components/kiosk/media_library/_artists_container.html",
            "back_url": "/kiosk/library",
            "artists": artists,
            "group": group,
        })
        if _is_htmx_request(request):
            return templates.TemplateResponse("components/kiosk/_media_library.html", context)
        context["kiosk_mode"] = True
        return templates.TemplateResponse("pages/kiosk/library.html", context)

    if artist_id:
        albums = subsonic_service.list_albums_for_artist(artist_id)
        context.update({
            "title": artist_name or "Albums",
            "content_template": "components/kiosk/media_library/_albums_container.html",
            "back_url": f"/kiosk/library?group={group}" if group else "/kiosk/library",
            "albums": albums or [],
            "artist": {"name": artist_name or "Unknown Artist"},
            "group": group,
        })
        if _is_htmx_request(request):
            return templates.TemplateResponse("components/kiosk/_media_library.html", context)
        context["kiosk_mode"] = True
        return templates.TemplateResponse("pages/kiosk/library.html", context)

    if _is_htmx_request(request):
        return templates.TemplateResponse("components/kiosk/_media_library.html", context)
    context["kiosk_mode"] = True
    return templates.TemplateResponse("pages/kiosk/library.html", context)


@router.post("/kiosk/library/play/{album_id}", response_class=HTMLResponse)
async def kiosk_library_play_album(request: Request, album_id: str):
    playback_service = get_service("playback_service")
    ok = await playback_service.load_from_album_id(album_id)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Failed to load album {album_id}")

    if _is_htmx_request(request):
        return templates.TemplateResponse(
            "components/kiosk/_player_status.html",
            {"request": request, "config": config},
        )
    return templates.TemplateResponse(
        "pages/kiosk/player.html",
        {"request": request, "config": config, "kiosk_mode": True},
    )


@router.get("/kiosk/nfc-client-select", response_class=HTMLResponse)
async def kiosk_nfc_client_select(
    request: Request,
    album_id: str = Query(...),
    album_name: str = Query(...),
):
    context = {
        "request": request,
        "config": config,
        "album_id": album_id,
        "album_name": album_name,
    }
    if _is_htmx_request(request):
        return templates.TemplateResponse("components/kiosk/_nfc_client_select.html", context)
    context["kiosk_mode"] = True
    return templates.TemplateResponse("pages/kiosk/nfc.html", context)


@router.get("/kiosk/nfc", response_class=HTMLResponse)
async def kiosk_nfc_partial(
    request: Request,
    album_id: str = Query(...),
    album_name: str = Query(...),
    client_id: str = Query(None),
):
    context = {
        "request": request,
        "config": config,
        "album_id": album_id,
        "album_name": album_name,
        "client_id": client_id,
    }
    if _is_htmx_request(request):
        return templates.TemplateResponse("components/kiosk/_nfc_encoding.html", context)
    context["kiosk_mode"] = True
    return templates.TemplateResponse("pages/kiosk/nfc.html", context)

