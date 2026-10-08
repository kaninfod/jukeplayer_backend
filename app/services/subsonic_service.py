import requests
from typing import List, Dict, Any, Optional
import logging
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
        
    def get_cover_proxy_url(self, album_id: str) -> str:
        """
        Return the local proxy URL for cover art so the browser never hits Subsonic directly.
        This avoids Basic Auth prompts and respects CSP by staying same-origin.
        The proxy ROUTE and all image/cache work live in CoverService
        (app/services/cover_service.py) — this URL string is that route's
        contract and is built here because gonic-side album methods embed it.
        """
        return f"/api/subsonic/cover/{album_id}"

    def cover_art_bytes(self, album_id: str) -> bytes:
        """The RAW getCoverArt response — CoverService's fetch seam (the
        API client owns auth/transport; the image/caching work is not)."""
        return self._api_request("getCoverArt", {"id": album_id}).content

    def search_song(self, query: str) -> Dict[str, Any]:
        logger.info(f"SubsonicService: Searching for song: {query}")
        data = self._api_request("search3", {"query": query})
        data = data.json()
        songs = data.get("searchResult3", {}).get("song", [])
        if not songs:
            logger.warning("SubsonicService: No songs found.")
            raise Exception("No songs found.")
        return songs[0]

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

    # All four reads below (search_song / get_album_tracks / get_album_info /
    # get_song_info) are deliberately NOT lru_cached: album-level tag data
    # changes out of band now (tagtool consolidations, gonic rescans) and a
    # method cache holds it until restart — the same stale-until-restart bug
    # the artist listing had. Cross-request caching belongs to the
    # service-level cache owners (ArtistMetadataService), not to decorators.
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
