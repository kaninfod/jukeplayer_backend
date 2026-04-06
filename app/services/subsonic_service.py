import requests
from typing import List, Dict, Any, Optional
import logging
from functools import lru_cache
import time

logger = logging.getLogger(__name__)

class SubsonicService:    
    def __init__(self, config=None):
        """
        Initialize SubsonicService with dependency injection.
        
        Args:
            config: Configuration object for Subsonic settings
        """
        # Inject config dependency - no more direct import needed
        if config:
            self.config = config
        else:
            # Fallback for backward compatibility - this will be removed later
            from app.config import config as default_config
            self.config = default_config

        self.base_url = self.config.SUBSONIC_URL.rstrip("/")
        self.username = getattr(self.config, "SUBSONIC_USER", "jukebox")
        self.password = getattr(self.config, "SUBSONIC_PASS", "123jukepi")
        self.client = getattr(self.config, "SUBSONIC_CLIENT", "jukebox")
        self.api_version = getattr(self.config, "SUBSONIC_API_VERSION", "1.16.1")
        # Optional Basic Auth at proxy (NPM) for all Subsonic requests
        self.basic_user = getattr(self.config, "SUBSONIC_PROXY_BASIC_USER", "")
        self.basic_pass = getattr(self.config, "SUBSONIC_PROXY_BASIC_PASS", "")
        logger.info(f"SubsonicService initialized with dependency injection for {self.base_url} as {self.username}")

    def _api_params(self) -> Dict[str, str]:
        import hashlib, random, string
        salt = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        token = hashlib.md5((self.password + salt).encode('utf-8')).hexdigest()
        return {
            "u": self.username,
            "t": token,
            "s": salt,
            "c": self.client,
            "v": self.api_version,
            "f": "json"
        }

    def _api_request(self, endpoint: str, extra_params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        params = self._api_params()
        if extra_params:
            params.update(extra_params)
        url = f"{self.base_url}/rest/{endpoint}"
        logger.debug(f"SubsonicService: Requesting {url}")
        auth = None
        if self.basic_user and self.basic_pass:
            auth = (self.basic_user, self.basic_pass)
        
        try:
            resp = requests.get(url, params=params, timeout=self.config.HTTP_REQUEST_TIMEOUT, auth=auth)
            resp.raise_for_status()  # Raises HTTPError for bad status codes
            return resp
        except requests.exceptions.Timeout as e:
            logger.error(f"❌ Subsonic timeout ({self.config.HTTP_REQUEST_TIMEOUT}s) for {endpoint}: {e}", exc_info=True)
            raise
        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ Failed to connect to Subsonic at {self.base_url}: {e}", exc_info=True)
            raise
        except requests.exceptions.HTTPError as e:
            logger.error(f"❌ Subsonic HTTP error for {endpoint}: {e.response.status_code} {e.response.text[:200]}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"❌ Subsonic request failed for {endpoint}: {e}", exc_info=True)
            raise

    
    def get_stream_url(self, track: dict) -> str:
        track_id = track.get('id')
        if not track_id:
            return None
        # Use _api_params for authentication
        params = self._api_params()
        params['id'] = track_id
        # Remove 'f' param for binary endpoints
        params.pop('f', None)
        # Build URL with token-based authentication using SUBSONIC_URL
        from urllib.parse import urlencode
        url = f"{self.base_url.rstrip('/')}/rest/stream?{urlencode(params)}"
        return url
        
    def get_cover_url(self, album_id: str) -> str:
        params = self._api_params()
        params['id'] = album_id
        # Remove 'f' param for binary endpoints
        params.pop('f', None)
        from urllib.parse import urlencode
        url = f"{self.base_url}/rest/getCoverArt?{urlencode(params)}"
        return url

    def get_cover_proxy_url(self, album_id: str) -> str:
        """
        Return the local proxy URL for cover art so the browser never hits Subsonic directly.
        This avoids Basic Auth prompts and respects CSP by staying same-origin.
        """
        return f"/api/subsonic/cover/{album_id}"

    # --- New unified cover pipeline helpers ---
    def _cover_dir(self, album_id: str) -> str:
        import os
        base = getattr(self.config, "STATIC_FILE_PATH", "static_files")
        return os.path.join(base, "covers", str(album_id))

    def _default_cover_dir(self) -> str:
        import os
        base = getattr(self.config, "STATIC_FILE_PATH", "static_files")
        return os.path.join(base, "covers", "_default")

    def _cover_paths(self, album_id: str, size: int) -> dict:
        import os
        d = self._cover_dir(album_id)
        return {
            "webp": os.path.join(d, f"cover-{size}.webp"),
            "jpg": os.path.join(d, f"cover-{size}.jpg"),
        }

    def _default_cover_paths(self, size: int) -> dict:
        import os
        d = self._default_cover_dir()
        return {
            "webp": os.path.join(d, f"cover-{size}.webp"),
            "jpg": os.path.join(d, f"cover-{size}.jpg"),
        }

    def _ensure_dir(self, path: str) -> None:
        import os
        os.makedirs(path, exist_ok=True)

    def _center_square(self, image):
        w, h = image.size
        if w == h:
            return image
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        return image.crop((left, top, left + side, top + side))

    def _save_variants(self, pil_image, out_paths: dict, size: int) -> None:
        from PIL import Image
        img = self._center_square(pil_image.convert("RGB")).resize((size, size), Image.Resampling.LANCZOS)
        # Save WebP and JPEG
        try:
            img.save(out_paths["webp"], format="WEBP", quality=80)
        except Exception:
            pass
        try:
            img.save(out_paths["jpg"], format="JPEG", quality=85)
        except Exception:
            pass

    def _ensure_default_placeholder(self, size: int) -> None:
        # Generate a simple placeholder if not present
        from PIL import Image, ImageDraw
        import os
        paths = self._default_cover_paths(size)
        self._ensure_dir(self._default_cover_dir())
        if not (os.path.exists(paths["webp"]) or os.path.exists(paths["jpg"])):
            img = Image.new("RGB", (size, size), color=(240, 240, 240))
            draw = ImageDraw.Draw(img)
            # Simple music note placeholder
            draw.rectangle([(size*0.25, size*0.25), (size*0.75, size*0.75)], outline=(200,200,200), width=2)
            self._save_variants(img, paths, size)

    def ensure_cover(self, album_id: str, size: int = 180) -> str:
        """
        Ensure a static cover exists at static_files/covers/{album_id}/cover-{size}.webp|jpg.
        Returns a relative URL to the preferred WebP file if available, else JPEG, else default placeholder.
        """
        from io import BytesIO
        from PIL import Image
        import os

        # If file exists, return URL immediately
        paths = self._cover_paths(album_id, size)
        self._ensure_dir(self._cover_dir(album_id))
        if os.path.exists(paths["webp"]) or os.path.exists(paths["jpg"]):
            return self._cover_url(album_id, size)

        # Try to fetch original from Subsonic and generate variants
        try:
            resp = self._api_request("getCoverArt", {"id": album_id})
            img = Image.open(BytesIO(resp.content))
            self._save_variants(img, paths, size)
            return self._cover_url(album_id, size)
        except Exception:
            # Fallback to default placeholder
            self._ensure_default_placeholder(size)
            return self._default_cover_url(size)

    def ensure_cover_variants(self, album_id: str, sizes=(180, 512)) -> None:
        for s in sizes:
            try:
                self.ensure_cover(album_id, s)
            except Exception:
                pass

    def _cover_url(self, album_id: str, size: int, prefer: str = "webp") -> str:
        # Return relative URL under /assets
        ext = "webp" if prefer == "webp" else "jpg"
        # Prefer the one that exists
        import os
        paths = self._cover_paths(album_id, size)
        chosen = f"/assets/covers/{album_id}/cover-{size}.{ext}"
        if prefer == "webp" and not os.path.exists(paths["webp"]) and os.path.exists(paths["jpg"]):
            chosen = f"/assets/covers/{album_id}/cover-{size}.jpg"
        return chosen

    def _default_cover_url(self, size: int, prefer: str = "webp") -> str:
        import os
        paths = self._default_cover_paths(size)
        if prefer == "webp" and os.path.exists(paths["webp"]):
            return f"/assets/covers/_default/cover-{size}.webp"
        if os.path.exists(paths["jpg"]):
            return f"/assets/covers/_default/cover-{size}.jpg"
        # As a last resort, point to a proxy (should rarely happen)
        return f"/assets/covers/_default/cover-{size}.jpg"

    def get_cover_static_url(self, album_id: str, size: int = 180, absolute: bool = False, prefer: str = "webp") -> str:
        """Return a ready-to-use URL (ensuring generation if missing)."""
        import os
        rel = self.ensure_cover(album_id, size)
        if not absolute:
            return rel
        base = getattr(self.config, "PUBLIC_BASE_URL", "").rstrip("/")
        return f"{base}{rel}" if base else rel

    @lru_cache(maxsize=128)
    def search_song(self, query: str) -> Dict[str, Any]:
        logger.info(f"SubsonicService: Searching for song: {query}")
        data = self._api_request("search3", {"query": query})
        data = data.json()
        songs = data.get("searchResult3", {}).get("song", [])
        if not songs:
            logger.warning("SubsonicService: No songs found.")
            raise Exception("No songs found.")
        return songs[0]

    @lru_cache(maxsize=128)
    def get_album_tracks(self, album_id: str) -> List[Dict[str, Any]]:
        logger.info(f"SubsonicService: Getting album tracks for album_id: {album_id}")
        data = self._api_request("getMusicDirectory", {"id": album_id})
        data = data.json()
        directory = data.get("subsonic-response", {}).get("directory", {})
        if "child" not in directory:
            logger.warning(f"No tracks found for album_id: {album_id}")
            return []
        songs = directory["child"]
        # Filter only song entries (not folders/discs)
        songs = [s for s in songs if not s.get('isDir')]
        logger.info(f"SubsonicService: Found {len(songs)} tracks for album_id: {album_id}")
        return songs

    @lru_cache(maxsize=128)
    def get_album_info(self, album_id: str) -> Dict[str, Any]:
        logger.info(f"SubsonicService: Getting album info for album_id: {album_id}")
        data = self._api_request("getAlbum", {"id": album_id})
        data = data.json()
        album = data.get("subsonic-response", {}).get("album", {})
        return album

    @lru_cache(maxsize=128)
    def list_artists(self) -> list:
        """
        Return a list of all artists from Subsonic (id, name).
        """
        data = self._api_request("getMusicDirectory", {"id": "al-1"})
        data = data.json()
        logger.info(f"SubsonicService: Found {len(data.get('subsonic-response', {}).get('directory', {}).get('child', []))} artists from Subsonic")
        directory = data.get("subsonic-response", {}).get("directory", {})
        artists = directory.get("child", [])
        # Only include entries where isDir is True (artists are directories)
        return [
            {"id": artist.get("id"), "name": artist.get("title")}
            for artist in artists if artist.get('isDir', False)
        ]

    @lru_cache(maxsize=128)
    def list_albums_for_artist(self, artist_id: str) -> list:
        """
        Return a list of all albums for a given artist (id, name).
        """
        # Subsonic: getMusicDirectory with id=artist_id returns albums for that artist
        data = self._api_request("getMusicDirectory", {"id": artist_id})
        data = data.json()
        directory = data.get("subsonic-response", {}).get("directory", {})
        albums = directory.get("child", [])
        # Each album is a dict with 'id' and 'title'
        result = []
        for album in albums:
            if not album.get('isDir', False):
                continue
            aid = album.get("id")
            # Ensure a small cover for grids
            cover_small = self.get_cover_static_url(aid, 180, absolute=False)
            result.append({
                "id": aid,
                "name": album.get("title"),
                "year": album.get("year"),
                "cover_url": cover_small,
            })
        return result

    @lru_cache(maxsize=128)
    def get_song_info(self, track_id: str) -> Optional[Dict[str, str]]:
        """
        Fetch song info from Subsonic using getSong endpoint.
        Returns a dict with 'id', 'albumId', and 'artistId' if found, else None.
        """
        try:
            data = self._api_request("getSong", {"id": track_id})
            data = data.json()
            song = data.get("subsonic-response", {}).get("song", {})
            if not song:
                logger.warning(f"SubsonicService: No song found for id {track_id}")
                return None
            return {
                "id": song.get("id", "unknown"),
                "albumId": song.get("albumId", "unknown"),
                "artistId": song.get("artistId", "unknown")
            }
        except Exception as e:
            logger.error(f"SubsonicService: Failed to fetch song info for id {track_id}: {e}")
            return None


    def get_alphabetical_groups(self) -> List[Dict[str, str]]:
        """
        Return alphabetical groups for organizing artists.
        
        Returns:
            List of dicts with 'name' and 'range' keys
        """
        return [
            {"name": "A-D", "range": ("A", "D")},
            {"name": "E-H", "range": ("E", "H")},
            {"name": "I-L", "range": ("I", "L")},
            {"name": "M-P", "range": ("M", "P")},
            {"name": "Q-T", "range": ("Q", "T")},
            {"name": "U-Z", "range": ("U", "Z")}
        ]

    def get_artists_in_range(self, start_letter: str, end_letter: str) -> List[Dict[str, Any]]:
        """
        Get all artists whose names start with letters in the given range.
        
        Args:
            start_letter: Starting letter (e.g., 'A')
            end_letter: Ending letter (e.g., 'D')
            
        Returns:
            List of artist dicts with 'id' and 'name'
        """
        if not hasattr(self, '_cached_artists') or not self._cached_artists:
            self._cached_artists = self.list_artists()
        
        filtered_artists = []
        for artist in self._cached_artists:
            name = artist.get('name', '').upper()
            if name and start_letter <= name[0] <= end_letter:
                filtered_artists.append(artist)
        
        # Sort alphabetically
        filtered_artists.sort(key=lambda x: x.get('name', '').upper())
        return filtered_artists

    def cache_artists_data(self) -> None:
        """
        Cache all artists data for faster menu navigation.
        """
        logger.info("Caching artists data from Subsonic...")
        try:
            self._cached_artists = self.list_artists()
            logger.info(f"Cached {len(self._cached_artists)} artists")
        except Exception as e:
            logger.error(f"Failed to cache artists data: {e}")
            self._cached_artists = []

    def _fetch_and_cache_coverart(self, album_id: str, filename_prefix: str = None) -> Optional[str]:
        """
        Download and cache the album cover image from Subsonic.
        Returns the filename if successful, else None.
        
        Args:
            album_id: The album ID to fetch cover art for
            filename_prefix: Optional prefix for filename (e.g., RFID). If None, uses album_id
        """

        from PIL import Image
        from io import BytesIO
        import os

        try:
            response = self._api_request("getCoverArt", {"id": album_id})

            image = Image.open(BytesIO(response.content))
            image = image.convert('RGBA')
            image = image.resize((120, 120), Image.Resampling.LANCZOS)
            
            # Use album_id as filename if no prefix provided
            if filename_prefix:
                filename = f"{filename_prefix}.png"
            else:
                filename = f"{album_id}.png"
                
            # Use injected config instead of direct import
            cache_dir = getattr(self.config, "STATIC_FILE_PATH", "static_files")
            logger.info(f"SubsonicService: Caching album cover art to {cache_dir}")
            local_path = os.path.join(cache_dir, filename)
            image.save(local_path, format='PNG')
            logger.info(f"Cached and processed album cover: {local_path}")
            return filename
        except Exception as e:
            logger.warning(f"Failed to cache album cover from {album_id}: {e}")
            return None
        
    def add_or_update_album_entry_from_album_id(self, album_id: str):
        """
        Fetch album info from Subsonic and create album data structure.
        Returns the album data dict or None on failure.
        This is the core fetching logic without RFID dependency.
        """
        import json
        try:
            album_info = self.get_album_info(album_id)
            album_name = album_info.get('name', 'Unknown Album')
            artist_name = album_info.get('artist', 'Unknown Artist')
            year = album_info.get('year', None)
            
            # Fetch and cache cover art using audioPlaylistId as filename
            thumbnail_filename = self._fetch_and_cache_coverart(album_id)
            
            tracks_data = []
            tracks = self.get_album_tracks(album_id)
            
            for track in tracks:
                track_info = {
                    'title': track.get('title', 'Unknown Title'),
                    'duration': str(track.get('duration', '0:00')),
                    'track_number': track.get('track', 0),
                    'track_id': track.get('id', '')
                }
                tracks_data.append(track_info)
                
            album_data = {
                'album_name': album_name,
                'artist_name': artist_name,
                'year': year,
                'album_id': album_id,
                'thumbnail': thumbnail_filename,  # Now properly set!
                'tracks': json.dumps(tracks_data)
            }
            
            logger.info(f"SubsonicService: Fetched album data for {album_id}: {album_name} by {artist_name}")
            return album_data
            
        except Exception as e:
            logger.error(f"SubsonicService: Failed to fetch album data for {album_id}: {e}")
            return None

    def add_or_update_album_entry(self, rfid: str, audioPlaylistId: str):
        """
        Fetch album info from Subsonic, cache the cover, and upsert the album entry in the database.
        Returns the DB entry or None on failure.
        """
        from app.database.album_db import update_album_entry, create_album_entry, get_album_entry_by_rfid
        
        try:
            # Get the core album data using the new method
            album_data = self.add_or_update_album_entry_from_audioPlaylistId(audioPlaylistId)
            
            if not album_data:
                logger.error(f"SubsonicService: Failed to fetch album data for {audioPlaylistId}")
                return None
            
            # Add RFID-specific data (cover art caching)
            thumbnail_path = self._fetch_and_cache_coverart(audioPlaylistId, filename_prefix=rfid)
            album_data['thumbnail'] = thumbnail_path
            
            # Upsert logic
            logger.info(f"SubsonicService: Upserting album entry for RFID {rfid}: {album_data}")
            db_entry = get_album_entry_by_rfid(rfid)
            
            if db_entry:
                db_entry = update_album_entry(rfid, album_data)
            else:
                create_album_entry(rfid)
                db_entry = update_album_entry(rfid, album_data)
            return db_entry
            
        except Exception as e:
            logger.error(f"SubsonicService: Failed to add/update album entry for RFID {rfid}: {e}")
            return None

    def scrobble_now_playing(self, track_id: str) -> bool:
        """
        Notify Subsonic that a track is now playing (scrobble to Last.fm if configured).
        
        This sends a "now playing" notification to Subsonic, which will forward it to
        Last.fm if scrobbling is configured in Subsonic settings.
        
        API Reference: https://www.subsonic.org/pages/api.jsp#scrobble
        Endpoint: rest/scrobble (POST: id, submission=false for "now playing", time=current timestamp)
        
        Args:
            track_id: The Subsonic track ID to scrobble
            
        Returns:
            True if scrobble was successful, False otherwise
        """
        try:
            if not track_id:
                logger.warning("scrobble_now_playing: No track_id provided")
                return False
            
            # Get current time in milliseconds since epoch
            current_time_ms = int(time.time() * 1000)
            
            resp = self._api_request("scrobble", {
                "id": track_id,
                "submission": "true",
                "time": str(current_time_ms)
            })
            data = resp.json()
            
            # Check if the response indicates success
            if data.get("subsonic-response", {}).get("status") == "ok":
                logger.info(f"scrobble_now_playing: Successfully sent 'now playing' notification for track {track_id} to Last.fm at {current_time_ms}")
                return True
            else:
                error_msg = data.get("subsonic-response", {}).get("error", "Unknown error")
                logger.warning(f"scrobble_now_playing: Failed to send 'now playing' notification for track {track_id}: {error_msg}")
                return False
                
        except Exception as e:
            logger.error(f"scrobble_now_playing: Failed to scrobble track {track_id}: {e}")
            return False
