from fastapi import APIRouter, HTTPException, Response
from fastapi import Query
from app.core.service_container import get_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subsonic", tags=["subsonic"])

@router.get("/artists")
def get_all_artists():
    """Return all artists from SubsonicService."""
    try:
        subsonic_service = get_service("subsonic_service")
        artists = subsonic_service.list_artists()
        if artists is None:
            raise HTTPException(status_code=404, detail="No artists found")
        return artists
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch artists: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Failed to fetch artists: {e}")

@router.get("/artist/{id}")
def get_artist_albums(id: str):
    """Return all albums by artist (id) from SubsonicService."""
    try:
        subsonic_service = get_service("subsonic_service")
        albums = subsonic_service.list_albums_for_artist(id)
        if albums is None:
            raise HTTPException(status_code=404, detail="No albums found for artist")
        return albums
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch albums for artist {id}: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Failed to fetch albums for artist: {e}")

@router.get("/album/{id}")
def get_album_songs(id: str):
    """Return all songs on album (id) from SubsonicService."""
    try:
        subsonic_service = get_service("subsonic_service")
        songs = subsonic_service.get_album_tracks(id)
        if songs is None:
            raise HTTPException(status_code=404, detail="No songs found for album")
        return songs
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch songs for album {id}: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Failed to fetch songs for album: {e}")

@router.get("/cover/{album_id}")
def get_cover_art(album_id: str):
    """
    Proxy cover art through the jukebox API so the browser doesn't need
    credentials for the Gonic host. Uses SubsonicService with optional
    proxy Basic auth configured in ENV.
    """
    subsonic_service = get_service("subsonic_service")
    try:
        resp = subsonic_service._api_request("getCoverArt", {"id": album_id})
        content_type = resp.headers.get("Content-Type", "image/png")
        return Response(content=resp.content, media_type=content_type)
    except Exception as e:
        logger.error(f"Failed to fetch cover art for {album_id}: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Failed to fetch cover art: {e}")


@router.get("/album_info/{id}")
def get_album_info(id: str):
    """Return album metadata (name, artist, etc.) for the given album id."""
    subsonic_service = get_service("subsonic_service")
    try:
        album = subsonic_service.get_album_info(id)
        if not album:
            raise HTTPException(status_code=404, detail="Album not found")
        return album
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch album info for {id}: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Failed to fetch album info: {e}")


# @router.get("/api/images/covers/{album_id}")
# def get_cover_static_url(album_id: str, size: int = Query(180, ge=64, le=1024), absolute: bool = Query(False)):
#     """
#     Return the static cover URL for a given album id and size. Ensures generation if missing.
#     """
#     subsonic_service = get_service("subsonic_service")
#     try:
#         url = subsonic_service.get_cover_static_url(album_id, size=size, absolute=absolute)
#         return {"url": url}
#     except Exception as e:
#         raise HTTPException(status_code=502, detail=f"Failed to resolve cover URL: {e}")
