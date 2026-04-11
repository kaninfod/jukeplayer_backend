from fastapi import APIRouter, HTTPException, Response
from fastapi import Query
from app.core.service_container import get_service
from app.schemas import Artist, Album, Song, AlbumInfo
from typing import List
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subsonic", tags=["subsonic"])

@router.get("/artists", response_model=List[Artist])
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

@router.get("/artist/{id}", response_model=List[Album])
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

@router.get("/album/{id}", response_model=List[Song])
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


from fastapi import Request
from fastapi.responses import FileResponse
import os

@router.get("/cover/{album_id}")
def get_cover_art(
    album_id: str,
    source: str = Query("local", regex="^(local|subsonic)$"),
    size: int = Query(180, ge=64, le=1024)
):
    """
    Serve album cover art, defaulting to local cache, with optional fallback to Subsonic.
    - source=local: Use local cache, fallback to Subsonic if missing and cache result.
    - source=subsonic: Always fetch from Subsonic and cache result.
    """
    subsonic_service = get_service("subsonic_service")
    covers_dir = subsonic_service._cover_dir(album_id)
    paths = subsonic_service._cover_paths(album_id, size)
    # Try local first
    if source == "local":
        # If local exists, serve it
        if os.path.exists(paths["webp"]):
            return FileResponse(paths["webp"], media_type="image/webp")
        if os.path.exists(paths["jpg"]):
            return FileResponse(paths["jpg"], media_type="image/jpeg")
        # If not, try to generate/copy from Subsonic and cache
        try:
            subsonic_service.ensure_cover(album_id, size)
            # Try again after generation
            if os.path.exists(paths["webp"]):
                return FileResponse(paths["webp"], media_type="image/webp")
            if os.path.exists(paths["jpg"]):
                return FileResponse(paths["jpg"], media_type="image/jpeg")
        except Exception as e:
            logger.warning(f"Could not auto-cache cover for {album_id}: {e}")
        # Fallback to default placeholder
        default_paths = subsonic_service._default_cover_paths(size)
        if os.path.exists(default_paths["webp"]):
            return FileResponse(default_paths["webp"], media_type="image/webp")
        if os.path.exists(default_paths["jpg"]):
            return FileResponse(default_paths["jpg"], media_type="image/jpeg")
        raise HTTPException(status_code=404, detail="Cover not found and could not generate placeholder.")
    elif source == "subsonic":
        # Always fetch from Subsonic, cache result, then serve
        try:
            subsonic_service.ensure_cover(album_id, size)
            if os.path.exists(paths["webp"]):
                return FileResponse(paths["webp"], media_type="image/webp")
            if os.path.exists(paths["jpg"]):
                return FileResponse(paths["jpg"], media_type="image/jpeg")
        except Exception as e:
            logger.error(f"Failed to fetch cover from Subsonic for {album_id}: {e}", exc_info=True)
        # Fallback to default placeholder
        default_paths = subsonic_service._default_cover_paths(size)
        if os.path.exists(default_paths["webp"]):
            return FileResponse(default_paths["webp"], media_type="image/webp")
        if os.path.exists(default_paths["jpg"]):
            return FileResponse(default_paths["jpg"], media_type="image/jpeg")
        raise HTTPException(status_code=404, detail="Cover not found and could not generate placeholder.")


@router.get("/album_info/{id}", response_model=AlbumInfo)
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
