
import logging

from app.core import EventType, Event
from app.core.event_factory import EventFactory
from typing import List, Dict, Optional
from app.config import config
from app.services.media_player_service import PlaylistManager, PlaylistItem



logger = logging.getLogger(__name__)


class PlaybackService:
    def __init__(self, screen_manager, player, album_db, subsonic_service, event_bus):
        """
        Initialize PlaybackService with dependency injection.
        
        Args:
            player: MediaPlayerService instance for playback control
            album_db: AlbumDatabase instance for album data operations
            subsonic_service: SubsonicService instance for music provider operations
            event_bus: EventBus instance for event communication
        """
        # Inject all dependencies
        #self.screen_manager = screen_manager
        self.player = player
        self.album_db = album_db
        self.subsonic_service = subsonic_service
        self.event_bus = event_bus
        self._setup_event_subscriptions()
        
        logger.info("PlaybackService initialized with dependency injection.")
    
    def _setup_event_subscriptions(self):
        """Setup all event subscriptions using injected event_bus"""
        self.event_bus.subscribe(EventType.RFID_READ, self.load_rfid)
        self.event_bus.subscribe(EventType.PLAY_ALBUM, self._handle_play_album)
        self.event_bus.subscribe(EventType.ENCODE_CARD, self._encode_card)
        
        # Use wrapper handlers for playback control events to route to correct device
        self.event_bus.subscribe(EventType.TOGGLE_REPEAT, self._handle_toggle_repeat)
        self.event_bus.subscribe(EventType.TRACK_FINISHED, self._handle_track_finished)
        self.event_bus.subscribe(EventType.PREVIOUS_TRACK, self._handle_previous_track)
        self.event_bus.subscribe(EventType.NEXT_TRACK, self._handle_next_track)
        self.event_bus.subscribe(EventType.PLAY_TRACK, self._handle_play_track)
        self.event_bus.subscribe(EventType.PLAY_PAUSE, self._handle_play_pause)
        self.event_bus.subscribe(EventType.STOP, self._handle_stop)
        self.event_bus.subscribe(EventType.VOLUME_UP, self._handle_volume_up)
        self.event_bus.subscribe(EventType.VOLUME_DOWN, self._handle_volume_down)
        self.event_bus.subscribe(EventType.SET_VOLUME, self._handle_set_volume)
        self.event_bus.subscribe(EventType.VOLUME_MUTE, self._handle_volume_mute)
        # Note: SWITCH_DEVICE is now handled via API endpoints, not event subscriptions
    
    # Event wrapper handlers - route to correct device instance
    async def _handle_toggle_repeat(self, event):
        player = self._get_player_instance_for_event(event)
        return await player.toggle_repeat(event)
    
    async def _handle_track_finished(self, event):
        player = self._get_player_instance_for_event(event)
        return await player.next_track(event, force=True)
    
    async def _handle_previous_track(self, event):
        player = self._get_player_instance_for_event(event)
        return await player.previous_track(event)
    
    async def _handle_next_track(self, event):
        player = self._get_player_instance_for_event(event)
        return await player.next_track(event)
    
    async def _handle_play_track(self, event):
        player = self._get_player_instance_for_event(event)
        return await player.play_track(event)
    
    async def _handle_play_pause(self, event):
        player = self._get_player_instance_for_event(event)
        return await player.play_pause(event)
    
    async def _handle_stop(self, event):
        player = self._get_player_instance_for_event(event)
        return await player.stop(event)
    
    async def _handle_volume_up(self, event):
        player = self._get_player_instance_for_event(event)
        return await player.handle_volume_up(event)
    
    async def _handle_volume_down(self, event):
        player = self._get_player_instance_for_event(event)
        return await player.handle_volume_down(event)
    
    async def _handle_set_volume(self, event):
        player = self._get_player_instance_for_event(event)
        return await player._on_volume_event(event)
    
    async def _handle_volume_mute(self, event):
        player = self._get_player_instance_for_event(event)
        return await player.handle_volume_mute(event) 

    async def _handle_play_album(self, event):
        player = self._get_player_instance_for_event(event)
        return await self.load_from_album_id(event.payload.get("album_id"), player_instance=player, start_track_index=event.payload.get("start_track_index", 0))
         

    def _get_player_instance_for_event(self, event):
        """
        Determine which MediaPlayerService instance should handle an event.
        
        Looks for client_id or device_name in the event payload, then uses ClientRegistry
        to find the right instance. Falls back to self.player if not found.
        """
        from app.core.service_container import get_service
        
        payload = event.payload if hasattr(event, 'payload') else {}
        client_id = payload.get('client_id')
        device_name = payload.get('device_name')
        
        client_registry = get_service("client_registry")
        
        # Try to find instance by client_id first (higher priority - explicit client control)
        if client_id:
            instance = client_registry.get_client_active_instance(client_id)
            if instance:
                logger.debug(f"Routed event to device '{instance.device_name}' via client_id {client_id}")
                return instance
        
        # Try to find instance by device_name (e.g., from backend events like TRACK_FINISHED)
        if device_name:
            instances = client_registry.list_player_instances()
            for inst in instances:
                if inst.device_name == device_name:
                    logger.debug(f"Routed event to device '{device_name}' via device_name in payload")
                    return inst
        
        # Fall back to default player
        logger.debug("No client_id or device_name in event, using default player")
        return self.player


    def get_stream_url_for_track(self, track: Dict) -> Optional[str]:
        return self.subsonic_service.get_stream_url(track)

    # def get_cover_url_for_track(self, album_id: str) -> Optional[str]:
    #     """
    #     Cover URL resolver for the current track.
    #     Returns the cover URL or None if not available.
    #     """

    #     if album_id:
    #         url = self.subsonic_service.get_cover_static_url(album_id, size=512, absolute=False)
    #         if url:
    #             return url
    #         # Fallback to proxy if static cover is not available
    #         return self.subsonic_service.get_cover_proxy_url(album_id)
    #     else:
    #         return None

    async def load_from_album_id(self, album_id, player_instance=None, start_track_index=0):
        """
        Load and start playback from an album_id using SubsonicService only.
        Args:
            album_id: The album identifier
            player_instance: Optional MediaPlayerService instance to load into (defaults to self.player)
            start_track_index: Optional track index to start playback from (default 0)
        Returns:
            True if successful, False otherwise
        """
        # Use provided instance or fall back to default player
        if player_instance is None:
            player_instance = self.player
        
        logger.info(f"Loading playlist for album_id: {album_id} into {player_instance.device_name} (starting at track {start_track_index})")
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
            # thumb_url = self.get_cover_url_for_track(album_info.get('id'))
            # playlist_metadata = []

            # playlist = PlaylistManager(name=album_info.get('name', ''))
            cover_url = self.subsonic_service.get_cover_proxy_url(album_id)
            player_instance.playlist_manager.clear()
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
                player_instance.playlist_manager.add_item(item)

            logger.info(f"Prepared playlist with {player_instance.playlist_manager.count()} tracks for album_id {album_id}")
            player_instance.playlist_manager.current_index = start_track_index
            
            await player_instance.play_current_track()
            self.event_bus.emit(
                EventFactory.notification({"message": f"Playing {album_info.get('name', '')}"})
            )

            return True
        except Exception as e:
            logger.error(f"Failed to load album_id {album_id} (start_track_index={start_track_index}): {e}")
            return False

    async def load_rfid(self, event: Event) -> bool:
        """Orchestrate the full playback pipeline from RFID scan using new album DB and SubsonicService, or perform NFC encoding if active."""
        from app.core.service_container import get_service
        
        rfid = event.payload.get('rfid')
        album_id = event.payload.get('album_id')
        client_id = event.payload.get('client_id')
        logger.info(f"RFID Card scanned with RFID: {rfid} and album_id: {album_id} and client_id: {client_id}")
        
        # Determine which instance to use via ClientRegistry
        client_registry = get_service("client_registry")
        player_instance = None
        
        if client_id:
            player_instance = client_registry.get_client_active_instance(client_id)
        
        # Fall back to default instance if client not controlling anything
        if player_instance is None:
            instances = client_registry.list_player_instances()
            player_instance = instances[0] if instances else self.player
        
        self.event_bus.emit(
            EventFactory.notification({"message": f"RFID: {rfid}"})
        )
        
        if not album_id:
            logger.info(f"No album info on card, RFID {rfid}")
            album_id = self.album_db.get_album_id_by_rfid(rfid)

        if not album_id:
            logger.info(f"No album mapping found for RFID {rfid} in DB")
            self.event_bus.emit(
                EventFactory.notification({"message": f"No album mapped to this RFID. You should fix that!"})
            )
            
        else:
            logger.info(f"Found album_id {album_id} for RFID {rfid}, loading album into {player_instance.device_name}...")
            self.album_db.set_album_mapping(str(rfid), album_id)
            await self.load_from_album_id(album_id, player_instance=player_instance)
        return True

    # async def load_album(self, event: Event) -> bool:
    #     """Load and start playback from an album via PLAY_ALBUM event.
        
    #     Args:
    #         event: Event with payload containing:
    #             - album_id: The album ID to play
    #             - start_track_index: Optional track index to start from (default 0)
    #             - client_id: Optional client ID to determine which instance to use
    #             - target_device: Optional explicit device to load into
        
    #     Returns:
    #         True if successful, False otherwise
    #     """
    #     from app.core.service_container import get_service
    #     logger.info(f"Received PLAY_ALBUM event with payload: {event.payload}")

    #     album_id = event.payload.get('album_id')
    #     start_track_index = event.payload.get('start_track_index', 0)
    #     client_id = event.payload.get('client_id')
    #     target_device = event.payload.get('target_device')
        

    #     if not album_id:
    #         logger.error("PLAY_ALBUM event received without album_id in payload")
    #         return False
        
    #     # Determine which instance to use via ClientRegistry
    #     client_registry = get_service("client_registry")
    #     player_instance = None
        
    #     if target_device:
    #         # Explicit device requested
    #         try:
    #             player_instance = client_registry.get_or_create_player_instance(target_device)
    #         except KeyError as e:
    #             logger.error(f"Invalid target_device: {e}")
    #             return False
    #     elif client_id:
    #         # Use client's active instance
    #         player_instance = client_registry.get_client_active_instance(client_id)
        
    #     # Fall back to default instance if none determined
    #     if player_instance is None:
    #         instances = client_registry.list_player_instances()
    #         player_instance = instances[0] if instances else self.player
            
    #     logger.info(f"Loading album via PLAY_ALBUM event: album_id={album_id}, start_track_index={start_track_index}, client_id={client_id}, target_device={target_device} into {player_instance.device_name}")
    #     return await self.load_from_album_id(album_id, player_instance=player_instance, start_track_index=start_track_index)

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

