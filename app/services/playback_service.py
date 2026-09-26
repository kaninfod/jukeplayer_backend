
import asyncio
import logging

from app.core import EventType, Event
from typing import List, Dict, Optional
from app.config import config
from app.services.media_player_service import PlaylistManager, PlaylistItem



logger = logging.getLogger(__name__)


class PlaybackService:
    def __init__(self, subsonic_service, event_bus):
        """
        Initialize PlaybackService with dependency injection.

        Args:
            subsonic_service: SubsonicService instance for music provider operations
            event_bus: EventBus instance for event communication
        """
        self.subsonic_service = subsonic_service
        self.event_bus = event_bus
        self._setup_event_subscriptions()

        logger.info("PlaybackService initialized with dependency injection.")

    def _setup_event_subscriptions(self):
        """Setup all event subscriptions using injected event_bus"""
        self.event_bus.subscribe(EventType.RFID_READ, self.load_rfid)


    def get_stream_url_for_track(self, track: Dict) -> Optional[str]:
        return self.subsonic_service.get_stream_url(track)

    def _resolve_default_player(self):
        """Return the default speaker's player, or None (logs why)."""
        from app.core.service_container import get_service
        speaker = get_service("speaker_broker_service").resolve_speaker()
        return speaker.mediaplayer if speaker else None

    async def load_from_album_id(self, album_id, player=None, start_track_index=0):
        """
        Load and start playback from an album_id using SubsonicService only.
        Args:
            album_id: The album identifier
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
            # Offloaded to a thread: this is a blocking HTTP call, and it used
            # to freeze the event loop (stalling every connected WS client).
            album_info = await asyncio.to_thread(self.subsonic_service.get_album_info, album_id)
            if not album_info:
                logger.error(f"Album info not found in Subsonic for {album_id}")
                return False
            tracks = album_info.get('song', '')
            if not tracks:
                logger.error(f"No tracks found in Subsonic for album_id {album_id}")
                return False

            # Ensure static cover variants exist (180/512). Non-blocking if it fails.
            try:
                await asyncio.to_thread(self.subsonic_service.ensure_cover_variants, album_id, (180, 512))
            except Exception:
                pass

            cover_url = self.subsonic_service.get_cover_proxy_url(album_id)
            player.playlist_manager.clear()
            for track in tracks:
                stream_url = self.get_stream_url_for_track(track)

                item = PlaylistItem(
                    track_id=track.get('id'),
                    stream_url=stream_url if stream_url else '',
                    duration=str(track.get('duration', 0)),
                    track_number=track.get('track', 0),
                    title=track.get('title'),
                    artist=album_info.get('artist', ''),
                    album=album_info.get('name', ''),
                    year=album_info.get('year', ''),
                    cover_url=cover_url
                )
                player.playlist_manager.add_item(item)

            logger.info(f"Prepared playlist with {player.playlist_manager.count()} tracks for album_id {album_id}")
            player.playlist_manager.current_index = start_track_index
            
            await player.play_current_track()

            return True
        except Exception as e:
            logger.error(f"Failed to load album_id {album_id} (start_track_index={start_track_index}): {e}")
            return False

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

