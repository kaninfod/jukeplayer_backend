from io import BytesIO

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

    def _api_request(self, endpoint: str, extra_params: Optional[Dict[str, str]] = None, retries: int = 1) -> Dict[str, Any]:
        """GET a Subsonic endpoint. Transient failures (connection reset,
        timeout) are retried once with a short backoff; HTTP errors are not."""
        params = self._api_params()
        if extra_params:
            params.update(extra_params)
        url = f"{self.base_url}/rest/{endpoint}"
        logger.debug(f"SubsonicService: Requesting {url}")

        last_transient_exc = None
        for attempt in range(retries + 1):
            try:
                resp = requests.get(url, params=params, timeout=self.config.HTTP_REQUEST_TIMEOUT)
                resp.raise_for_status()  # Raises HTTPError for bad status codes
                return resp
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                # Transient: RemoteDisconnected, read timeouts, connection resets
                last_transient_exc = e
                if attempt < retries:
                    logger.warning(f"⚠️  Subsonic {endpoint} transient error (attempt {attempt + 1}/{retries + 1}): {e} — retrying")
                    time.sleep(0.5)
                    continue
            except requests.exceptions.HTTPError as e:
                logger.error(f"❌ Subsonic HTTP error for {endpoint}: {e.response.status_code} {e.response.text[:200]}", exc_info=True)
                raise
            except Exception as e:
                logger.error(f"❌ Subsonic request failed for {endpoint}: {e}", exc_info=True)
                raise

        logger.error(f"❌ Subsonic {endpoint} failed after {retries + 1} attempts: {last_transient_exc}", exc_info=True)
        raise last_transient_exc

    
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


    def get_cover_rgb565(self, album_id: str, size: int = 180) -> Optional[bytes]:
        """
        Return a size x size RGB565 raw image for the ILI9488 display.
        Device expects framebuf.RGB565: two bytes per pixel, little-endian.
        """
        from PIL import Image
        import os

        self.ensure_cover(album_id, size)

        paths = self._cover_paths(album_id, size)
        img_path = None
        for candidate in ("webp", "jpg"):
            p = paths.get(candidate)
            if p and os.path.exists(p):
                img_path = p
                break

        if not img_path:
            self._ensure_default_placeholder(size)
            paths = self._default_cover_paths(size)
            for candidate in ("webp", "jpg"):
                p = paths.get(candidate)
                if p and os.path.exists(p):
                    img_path = p
                    break

        if not img_path:
            logger.error(f"[COVER] no image file found for {album_id}")
            return None

        try:
            img = Image.open(img_path).convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            logger.exception(f"[COVER] failed to open {img_path}")
            return None

        packed = bytearray()
        for r, g, b in img.getdata():
            rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            packed.append(rgb565 & 0xFF)       # low byte first (little-endian)
            packed.append((rgb565 >> 8) & 0xFF) # high byte second

        return bytes(packed)


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

    def list_artists(self) -> list:
        """
        Return a list of all artists from Subsonic (id, name).
        NOTE: deliberately NOT lru_cached — the artist list must reflect new
        gonic albums without a restart; caching/refresh is the
        ArtistMetadataService's job now.
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

    def search_artists(self, query: str, count: int = 50) -> list:
        """search ARTISTS ONLY. IMPORTANT (measured on gonic 0.22): search2
        returns artist ids in the DIRECTORY-TREE id-space ('al-*') — the same
        space the library's artist cards / getMusicDirectory flow uses.
        search3/getArtists return entity ids ('ar-*') that getMusicDirectory
        resolves to an album+tracks instead — so search2 is the RIGHT call."""
        data = self._api_request(
            "search2",
            {"query": query, "artistCount": count, "albumCount": 0, "songCount": 0},
        ).json()
        raw = data.get("subsonic-response", {}).get("searchResult2", {}).get("artist", []) or []
        artists = [{"id": a.get("id"), "name": a.get("name")} for a in raw]
        logger.info(f"SubsonicService: search2 '{query}' -> {len(artists)} artists")
        return artists

    def artists_with_counts(self) -> list:
        """getArtists returns the entity-space (ar-* ids) WITH albumCount —
        richer metadata; the caller joins by name onto the directory flow."""
        data = self._api_request("getArtists").json()
        index = data.get("subsonic-response", {}).get("artists", {}).get("index", []) or []
        flat = []
        for block in index:
            for artist in block.get("artist", []) or []:
                flat.append({
                    "id": artist.get("id"),
                    "name": artist.get("name"),
                    "albumCount": artist.get("albumCount", 0),
                })
        return flat

    def list_genres(self) -> list:
        """getGenres rows (the genre chips' data): value, albumCount, songCount."""
        data = self._api_request("getGenres").json()
        genres = data.get("subsonic-response", {}).get("genres", {}).get("genre", []) or []
        return [
            {"value": g.get("value"),
             "albumCount": g.get("albumCount", 0),
             "songCount": g.get("songCount", 0)}
            for g in genres
        ]

    def list_all_albums(self, page_size: int = 10000) -> list:
        """Every album in the collection in one response. Measured on gonic
        0.22: 608 albums arrived whole for size=10000 — so the warm-up's
        per-artist dominant-genre vote is a loop over THIS list instead of
        a getMusicDirectory + getAlbum call per artist. The offset loop
        only exists so a much larger library pages cleanly."""
        offset, out = 0, []
        while True:
            data = self._api_request(
                "getAlbumList2",
                {"type": "alphabeticalByName", "size": page_size, "offset": offset},
            ).json()
            batch = data.get("subsonic-response", {}).get("albumList2", {}).get("album", []) or []
            out.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        return out

    def artist_dominant_genre(self, dir_id: str) -> Optional[str]:
        """The artist's primary genre = the most common genre among the
        artist's albums (each album's genres ride its own tags, exposed via
        getAlbum). Returns None when nothing has genre data."""
        from collections import Counter
        counter: Counter = Counter()
        data = self._api_request("getMusicDirectory", {"id": dir_id}).json()
        children = data.get("subsonic-response", {}).get("directory", {}).get("child", []) or []
        album_ids = [c.get("id") for c in children if c.get("isDir")]
        for album_id in album_ids:
            try:
                album = self.get_album_info(album_id)
                for genre in (album.get("genres") or []):
                    if genre.get("name"):
                        counter[genre["name"]] += 1
            except Exception as e:
                logger.debug(f"artist_dominant_genre: album {album_id} failed: {e}")
        if not counter:
            return None
        return counter.most_common(1)[0][0]

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
            cover_small = self.get_cover_proxy_url(aid) #self.get_cover_static_url(aid, 180, absolute=False)
            result.append({
                "id": aid,
                "name": album.get("title"),
                "year": album.get("year"),
                "cover_url": cover_small,
            })
        return result

    def list_albums_by_genre(self, genre: str, limit: int = 500) -> list:
        """Album grid for the A-Z directory's genre chips (target = ?genre=).
        getAlbumList2 type=byGenre returns the same al-* id-space the artist
        view plays from. Measured on gonic 0.22: chip albumCount matches the
        returned rows exactly (Rock 178 = 178), rows carry artist/year and
        come alphabetical, slash-genres ('Rock/Pop') work, so a single
        size=500 call covers the whole genre — no pagination for this
        collection's scale."""
        data = self._api_request("getAlbumList2", {"type": "byGenre", "genre": genre, "size": limit})
        albums = data.json().get("subsonic-response", {}).get("albumList2", {}).get("album", [])
        result = []
        for album in albums:
            aid = album.get("id")
            result.append({
                "id": aid,
                "name": album.get("name"),
                "artist": album.get("artist"),  # multi-artist grid: artist must show
                "year": album.get("year"),
                "cover_url": self.get_cover_proxy_url(aid),
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
                "submission": "false",  # now-playing notice, NOT a played-scrobble
                "time": str(current_time_ms)
            })
            data = resp.json()

            # Check if the response indicates success
            if data.get("subsonic-response", {}).get("status") == "ok":
                logger.info(f"scrobble_now_playing: Sent now-playing notification for track {track_id}")
                return True
            else:
                error_msg = data.get("subsonic-response", {}).get("error", "Unknown error")
                logger.warning(f"scrobble_now_playing: Failed to send 'now playing' notification for track {track_id}: {error_msg}")
                return False
                
        except Exception as e:
            logger.error(f"scrobble_now_playing: Failed to scrobble track {track_id}: {e}")
            return False
