
import asyncio
import logging

from app.core import EventType, Event
from typing import List, Dict, Optional
from app.config import config
from app.playback.media_player_service import PlaylistManager, PlaylistItem



logger = logging.getLogger(__name__)


class PlaybackService:
    def __init__(self, music_sources, event_bus):
        """
        Initialize PlaybackService with dependency injection.

        Args:
            music_sources: SourceRegistry (app/music_sources) for album/stream
                resolution — one seam, many sources
            event_bus: EventBus instance for event communication
        """
        self.music_sources = music_sources
        self.event_bus = event_bus
        self._setup_event_subscriptions()

        logger.info("PlaybackService initialized with dependency injection.")

    def _setup_event_subscriptions(self):
        """Setup all event subscriptions using injected event_bus"""
        self.event_bus.subscribe(EventType.RFID_READ, self.load_rfid)

    def _resolve_source(self, album_id):
        """ album_id may carry a namespace ('subsonic:al-678' — phase-2 cards)
        or be bare ('al-678' — every card encoded to date) → (source, raw_id)."""
        from app.music_sources.base import unqualify
        pid, raw_album_id = unqualify(album_id)
        return self.music_sources.get(pid), raw_album_id

    def _resolve_default_player(self):
        """Return the default speaker's player, or None (logs why)."""
        from app.core.service_container import get_service
        speaker = get_service("speaker_broker_service").resolve_speaker()
        return speaker.mediaplayer if speaker else None

    async def load_from_album_id(self, album_id, player=None, start_track_index=0):
        """
        Load and start playback from an album_id via the music-source seam.
        Args:
            album_id: The album identifier — bare (legacy cards/web routes,
                default source) or namespaced ("source:al-…", phase-2 cards)
            player: MediaPlayerService instance to load into (defaults to the
                default speaker's player)
            start_track_index: Optional track index to start playback from (default 0)
        Returns:
            True if successful, False otherwise
        """

        if player is None:
            player = self._resolve_default_player()
        if player is None:
            logger.error(f"load_from_album_id called without a player instance (album_id={album_id})")
            return False

        logger.info(f"Loading playlist for album_id: {album_id} into {player.device_name} (starting at track {start_track_index})")
        try:
            source, raw_album_id = self._resolve_source(album_id)

            # Offloaded to a thread: this is a blocking HTTP call, and it used
            # to freeze the event loop (stalling every connected WS client).
            album = await asyncio.to_thread(source.load_album, raw_album_id)
        except ValueError as e:
            logger.error(f"Album {album_id} could not be resolved via the source seam: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to load album_id {album_id} (start_track_index={start_track_index}): {e}")
            return False

        if not album.tracks:
            logger.error(f"No tracks found for album_id {album_id}")
            return False

        try:
            # Ensure static cover variants exist (180/512) — the subsonic
            # proxy-route contract for now. Non-blocking if it fails.
            if album.id and (album_id.startswith("subsonic:") or ":" not in album_id):
                from app.core.service_container import get_service
                cover_service = get_service("cover_service")
                await asyncio.to_thread(cover_service.ensure_cover_variants, raw_album_id, (180, 512))
        except Exception:
            pass

        player.playlist_manager.clear()
        for track in album.tracks:
            spec = source.stream_url(track.track_id)

            item = PlaylistItem(
                track_id=track.track_id,
                stream_url=spec.url if spec and spec.url else '',
                duration=track.duration,
                track_number=track.track_number,
                title=track.title,
                artist=album.artist,
                album=album.title,
                year=album.year,
                cover_url=album.cover_url
            )
            player.playlist_manager.add_item(item)

        logger.info(f"Prepared playlist with {player.playlist_manager.count()} tracks for album_id {album_id}")
        player.playlist_manager.current_index = start_track_index

        await player.play_current_track()

        return True

    async def load_rfid(self, event: Event) -> dict:
        """Handle RFID_READ events: play the album carried on the card.

        Cards are self-describing — the client reads album_id from the card
        and sends it in the event. There is no backend rfid→album database.
        Returns the structured result the HTTP/WS layers wrap."""
        from app.core.service_container import get_service

        rfid = event.payload.get('rfid')
        album_id = event.payload.get('album_id')
        client_id = event.payload.get('client_id')
        logger.info(f"RFID card scanned: rfid={rfid}, album_id={album_id}, client_id={client_id}")

        if not album_id:
            logger.warning(f"RFID {rfid} carries no album_id (unencoded card?) — ignoring")
            return {"ok": False, "error": f"Card {rfid} carries no album_id (unencoded card?)"}

        speaker = get_service("speaker_broker_service").resolve_speaker(client_id=client_id)
        player = speaker.mediaplayer if speaker else None
        if player is None:
            logger.error("RFID_READ received but no player available to load album into")
            return {"ok": False, "error": "No player available to load the album into"}

        logger.info(f"Loading album_id {album_id} from RFID {rfid} into {player.device_name}...")
        loaded = await self.load_from_album_id(album_id, player=player)
        if not loaded:
            return {"ok": False, "error": f"Could not load album '{album_id}' from card"}
        return {"ok": True, "message": f"Album '{album_id}' loaded from card"}

