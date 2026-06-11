from app.core import EventType, Event
import logging
from typing import Dict

from app.services.speakers_service import Speaker
logger = logging.getLogger(__name__)

class SpeakerBrokerService:
    def __init__(self, control_clients, speakers, event_bus):
        self.control_clients = control_clients
        self.speakers = speakers
        self.event_bus = event_bus

        self.event_bus.subscribe(EventType.REGISTER_CONTROL_CLIENT, self.handle_register_control_client)
        self.event_bus.subscribe(EventType.UNREGISTER_CONTROL_CLIENT, self.handle_unregister_control_client)
        self.event_bus.subscribe(EventType.ASSIGN_SPEAKER, self.handle_assign_speaker)

        self.event_bus.subscribe(EventType.PLAY_ALBUM, self.handle_play_album)
        self.event_bus.subscribe(EventType.PLAY_PAUSE, self.handle_play_pause)
        self.event_bus.subscribe(EventType.PREVIOUS_TRACK, self.handle_previous_track)
        self.event_bus.subscribe(EventType.NEXT_TRACK, self.handle_next_track)
        self.event_bus.subscribe(EventType.TRACK_FINISHED, self.handle_next_track)
        self.event_bus.subscribe(EventType.STOP, self.handle_stop)
        self.event_bus.subscribe(EventType.VOLUME_UP, self.handle_volume_up)
        self.event_bus.subscribe(EventType.VOLUME_DOWN, self.handle_volume_down)
        self.event_bus.subscribe(EventType.SET_VOLUME, self.handle_set_volume)
        self.event_bus.subscribe(EventType.VOLUME_MUTE, self.handle_volume_mute)
        self.event_bus.subscribe(EventType.TOGGLE_REPEAT, self.handle_toggle_repeat)
        self.event_bus.subscribe(EventType.PLAY_TRACK, self.handle_play_track)

        # event_bus.subscribe(EventType.VOLUME_CHANGED, self.handle_volume_changed)
        # event_bus.subscribe(EventType.NOTIFICATION, self.handle_notification)
        # event_bus.subscribe(EventType.BROADCAST_GENERIC_MESSAGE, self.handle_generic_message)


    async def handle_register_control_client(self, event: Event):
        payload = event.payload
        client_id = payload.get("client_id")
        logger.info(f"[SpeakerBrokerService] Handling REGISTER_CONTROL_CLIENT event for client_id: {client_id}")

        await self.control_clients.register(payload)

    async def handle_unregister_control_client(self, event: Event):
        payload = event.payload
        client_id = payload.get("client_id")
        logger.info(f"[SpeakerBrokerService] Handling UNREGISTER_CONTROL_CLIENT event for client_id: {client_id}")
        if not client_id:
            return
        
        self.control_clients.unregister(client_id)

    async def handle_assign_speaker(self, event: Event):
        payload = event.payload
        client_id = payload.get("client_id")
        speaker_name = payload.get("speaker_name")
        logger.info(f"[SpeakerBrokerService] Handling ASSIGN_SPEAKER event for client_id: {client_id} to speaker_name: {speaker_name}")
        if not client_id or not speaker_name:
            return
        
        self._remove_client_from_speakers(client_id)
        speaker = self._assign_client_to_speaker(client_id, speaker_name)
        logger.info(f"[SpeakerBrokerService] Assigned client_id: {client_id} to speaker_name: {speaker_name} with result: {speaker is not False}")
        if speaker:
            self.control_clients._clients[client_id].speaker_name = speaker_name
            await self.broadcast_context_to_clients(speaker)


    def _remove_client_from_speakers(self, client_id):
        result = False
        for speaker in self.speakers._speakers.values():
            if client_id in speaker.clients:
                speaker.clients.discard(client_id)
                result = True
        
        return result

    def _assign_client_to_speaker(self, client_id, speaker_name):
        speaker = self.speakers.get_speaker(speaker_name)
        if speaker:
            speaker.clients.add(client_id)
            return speaker
        return False

    def get_speaker_for_client(self, client_id):
        client = self.control_clients._clients.get(client_id)
        if not client:
            return None
        
        speaker_name = client.speaker_name
        speaker = self.speakers.get_speaker(speaker_name)
        if not speaker:
            return None
        
        return speaker

    async def broadcast_context_to_clients(self, speaker: Speaker):
        if not speaker:
            logger.warning(f"[SpeakerBrokerService]  No speaker provided for broadcasting message")
            return
        logger.info(f"[SpeakerBrokerService] Broadcasting message to speaker: {speaker.speaker_name} with clients: {speaker.clients}")
        for client_id in speaker.clients:
            client = self.control_clients._clients.get(client_id)
            result_payload = self._get_mediaplayer_context_for_client(client)
            if client:
                await client.send_callback({"type": "current_track", "payload": result_payload})

    async def broadcast_volume_to_clients(self, speaker: Speaker):
        if not speaker:
            logger.warning(f"[SpeakerBrokerService] No speaker provided for broadcasting message")
            return
        logger.info(f"[SpeakerBrokerService] Broadcasting volume message to speaker: {speaker.speaker_name} with clients: {speaker.clients}")
        volume = speaker.mediaplayer.volume_manager.volume
        for client_id in speaker.clients:
            client = self.control_clients._clients.get(client_id)

            if client:
                await client.send_callback(message = {"type": "volume_changed", "payload": volume})


    def _get_mediaplayer_context_for_client(self, client):
        speaker = self.get_speaker_for_client(client.client_id)

        if speaker and speaker.mediaplayer:
            if "minimal_messaging" in getattr(client, 'capabilities', []):
                shaped_payload = speaker.mediaplayer.get_context(minimal=True)
            else:
                shaped_payload = speaker.mediaplayer.get_context()
            return shaped_payload
        return None

    async def handle_play_album(self, event: Event):
        from app.core.service_container import get_service
        playback_service = get_service("playback_service")

        payload = event.payload
        album_id = payload.get("album_id")
        start_track_index = payload.get("start_track_index", 0)
        client_id = payload.get("client_id") # Needed only for the local logger string below

        async def play_album_action(mediaplayer):
            result = await playback_service.load_from_album_id(
                album_id, 
                player=mediaplayer, 
                start_track_index=start_track_index
            )
            logger.info(f"[SpeakerBrokerService] Loaded album_id: {album_id} for client_id: {client_id} with result: {result}")

        # Pass it to the helper
        await self._execute_media_action(event, "play_album", custom_action=play_album_action)

    async def handle_play_album_from_rfid(self, event: Event):
        from app.core.service_container import get_service
        playback_service = get_service("playback_service")

        payload = event.payload
        rfid = payload.get("rfid")
        start_track_index = payload.get("start_track_index", 0)
        client_id = payload.get("client_id") # Needed only for the local logger string below

        async def play_album_action(mediaplayer):
            result = await playback_service.load_rfid(
                rfid, 
                player=mediaplayer, 
                start_track_index=start_track_index
            )
            logger.info(f"[SpeakerBrokerService] Loaded rfid: {rfid} for client_id: {client_id} with result: {result}")

        # Pass it to the helper
        await self._execute_media_action(event, "play_album", custom_action=play_album_action)


    async def handle_play_pause(self, event: Event):
        await self._execute_media_action(event, "play_pause")

    async def handle_next_track(self, event: Event):
        await self._execute_media_action(event, "next_track")

    async def handle_previous_track(self, event: Event):
        await self._execute_media_action(event, "previous_track")

    async def handle_stop(self, event: Event):
        await self._execute_media_action(event, "stop")

    async def handle_volume_up(self, event: Event):
        await self._execute_media_action(event, "handle_volume_up", broadcaster=self.broadcast_volume_to_clients)

    async def handle_volume_down(self, event: Event):
        await self._execute_media_action(event, "handle_volume_down", broadcaster=self.broadcast_volume_to_clients)

    async def handle_set_volume(self, event: Event):
        await self._execute_media_action(event, "set_volume", broadcaster=self.broadcast_volume_to_clients)                

    async def handle_volume_mute(self, event: Event):
        await self._execute_media_action(event, "handle_volume_mute")    

    async def handle_toggle_repeat(self, event: Event):
        await self._execute_media_action(event, "toggle_repeat")                        

    async def handle_play_track(self, event: Event):


        async def play_track_action(mediaplayer):
            result = await mediaplayer.play_track(track_index=event.payload.get("track_index"))
            logger.info(f"[SpeakerBrokerService] Loaded track_index: {event.payload.get('track_index')}")
        
        await self._execute_media_action(event, "play_track", custom_action=play_track_action)  

    async def _execute_media_action(self, event: Event, action_name: str, custom_action=None, broadcaster=None):
        payload = event.payload
        client_id = payload.get("client_id")
        
        if not client_id:
            if "device_name" in payload:
                device_name = payload.get("device_name")
                speaker = self.speakers.get_speaker(device_name)
                logger.info(f"[SpeakerBrokerService] Handling {event.type} event for speaker: {speaker.speaker_name}")
        else:
            speaker = self.get_speaker_for_client(client_id)
            logger.info(f"[SpeakerBrokerService] Handling {event.type} event for client_id: {client_id} and speaker: {speaker.speaker_name if speaker else 'None'}")
        
        if speaker:
            mediaplayer = speaker.mediaplayer
        else:
            mediaplayer = None

        if mediaplayer and speaker:
            if custom_action:
                await custom_action(mediaplayer)
            else:
                action_method = getattr(mediaplayer, action_name)
                await action_method()
            
            if broadcaster is None:
                await self.broadcast_context_to_clients(speaker)
            else:
                await broadcaster(speaker)