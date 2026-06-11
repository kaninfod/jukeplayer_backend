
import logging

from app.core import EventType, Event
from app.core.event_factory import EventFactory
from typing import List, Dict, Optional
from app.config import config
from app.services.media_player_service import PlaylistManager, PlaylistItem



logger = logging.getLogger(__name__)


class PlaybackService:
    def __init__(self, player, album_db, subsonic_service, event_bus):
        """
        Initialize PlaybackService with dependency injection.
        
        Args:
            player: MediaPlayerService instance for playback control
            album_db: AlbumDatabase instance for album data operations
            subsonic_service: SubsonicService instance for music provider operations
            event_bus: EventBus instance for event communication
        """
        self.player = player
        self.album_db = album_db
        self.subsonic_service = subsonic_service
        self.event_bus = event_bus
        self._setup_event_subscriptions()
        
        logger.info("PlaybackService initialized with dependency injection.")
    
    def _setup_event_subscriptions(self):
        """Setup all event subscriptions using injected event_bus"""
        self.event_bus.subscribe(EventType.RFID_READ, self.load_rfid)
        # self.event_bus.subscribe(EventType.PLAY_ALBUM, self._handle_play_album)
        self.event_bus.subscribe(EventType.ENCODE_CARD, self._encode_card)
        

    def get_stream_url_for_track(self, track: Dict) -> Optional[str]:
        return self.subsonic_service.get_stream_url(track)

    async def load_from_album_id(self, album_id, player=None, start_track_index=0):
        """
        Load and start playback from an album_id using SubsonicService only.
        Args:
            album_id: The album identifier
            player_instance: Optional MediaPlayerService instance to load into (defaults to self.player)
            start_track_index: Optional track index to start playback from (default 0)
        Returns:
            True if successful, False otherwise
        """
        
        logger.info(f"Loading playlist for album_id: {album_id} into {player.device_name} (starting at track {start_track_index})")
        try:
            album_info = self.subsonic_service.get_album_info(album_id)
            if not album_info:
                logger.error(f"Album info not found in Subsonic for {album_id}")
                return False
            tracks = album_info.get('song', '')
            if not tracks:
                logger.error(f"No tracks found in Subsonic for album_id {album_id}")
                return False

            # Ensure static cover variants exist (180/512). Non-blocking if it fails.
            try:
                self.subsonic_service.ensure_cover_variants(album_id, sizes=(180, 512))
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
            self.event_bus.emit(
                EventFactory.notification({"message": f"Playing {album_info.get('name', '')}"})
            )

            return True
        except Exception as e:
            logger.error(f"Failed to load album_id {album_id} (start_track_index={start_track_index}): {e}")
            return False

    async def load_rfid(self, rfid, player, start_track_index=0) -> bool:
        """Orchestrate the full playback pipeline from RFID scan using new album DB and SubsonicService, or perform NFC encoding if active."""
        from app.core.service_container import get_service
        
        rfid = event.payload.get('rfid')
        album_id = event.payload.get('album_id')
        client_id = event.payload.get('client_id')
        logger.info(f"RFID Card scanned with RFID: {rfid} and album_id: {album_id} and client_id: {client_id}")
        
        # Determine which instance to use via ClientRegistry
        # client_registry = get_service("client_registry")
        # player_instance = None
        
        if client_id:
            player_instance = client_registry.get_client_active_instance(client_id)
        
        # Fall back to default instance if client not controlling anything
        if player is None:
            return False
        
        
        if not album_id:
            logger.info(f"No album info on card, RFID {rfid}")
            album_id = self.album_db.get_album_id_by_rfid(rfid)

        if not album_id:
            logger.info(f"No album mapping found for RFID {rfid} in DB")
            self.event_bus.emit(
                EventFactory.notification({"message": f"No album mapped to this RFID. You should fix that!"})
            )
            
        else:
            logger.info(f"Found album_id {album_id} for RFID {rfid}, loading album into {player.device_name}...")
            self.album_db.set_album_mapping(str(rfid), album_id)
            await self.load_from_album_id(album_id, player=player)
        return True

    def _encode_card(self, event: Event) -> bool:
        """Start an NFC encoding session for the given album_id."""
        from app.core.service_container import get_service
        nfc_state = get_service("nfc_encoding_state")
        if nfc_state.is_active():
            album_id = nfc_state.get_album_id()
            rfid = event.payload['rfid']
            logger.info(f"NFC encoding session started for album_id {album_id}")
            self.album_db.set_album_mapping(str(rfid), album_id)
            nfc_state.complete(rfid)
            
            self.event_bus.emit(
                EventFactory.show_screen_queued(
                    "message",
                    context={
                        "title": "Card Encoded!",
                        "icon_name": "contactless.png",
                        "message": f"RFID {rfid} mapped to album {album_id}",
                        "theme": "message_success"
                    },
                    duration=3
                )
            )
        return True

