from app.core import EventType, Event
import logging
from typing import Dict, Optional

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
        self.event_bus.subscribe(EventType.TRACK_CHANGED, self.handle_track_changed)
        self.event_bus.subscribe(EventType.VOLUME_CHANGED, self.handle_volume_changed)

    async def handle_volume_changed(self, event: Event):
        """A backend reported a device-side volume change (Google Home app,
        hardware buttons, or the initial status on connect). Update local
        state and push it to the speaker's clients. Read-back only — never
        written back to the device."""
        payload = event.payload
        device_name = payload.get("device_name")
        speaker = self.speakers.get_speaker(speaker_name=device_name) if device_name else None
        if not speaker or not speaker.mediaplayer:
            logger.warning(f"[SpeakerBrokerService] VOLUME_CHANGED for unknown device: {device_name}")
            return
        speaker.mediaplayer.volume_manager.set_local_volume(
            payload.get("volume"), payload.get("muted"))
        await self.broadcast_volume_to_clients(speaker)

    async def handle_track_changed(self, event: Event):
        """A player published a state update (e.g. after a backend switch) —
        push fresh context to its speaker's clients."""
        device_name = event.payload.get("device_name")
        speaker = self.speakers.get_speaker(speaker_name=device_name) if device_name else self.speakers.get_default_speaker()
        if speaker:
            await self.broadcast_context_to_clients(speaker)


    async def handle_register_control_client(self, event: Event):
        payload = event.payload
        client_id = payload.get("client_id")
        logger.info(f"[SpeakerBrokerService] Handling REGISTER_CONTROL_CLIENT event for client_id: {client_id}")

        return await self.control_clients.register(payload)

    async def handle_unregister_control_client(self, event: Event):
        payload = event.payload
        client_id = payload.get("client_id")
        logger.info(f"[SpeakerBrokerService] Handling UNREGISTER_CONTROL_CLIENT event for client_id: {client_id}")
        if not client_id:
            return

        # A late cleanup from a superseded connection must not delete a live
        # re-registration (web clients reuse their client_id across reconnects).
        websocket = payload.get("websocket")
        client = self.control_clients._clients.get(client_id)
        if client and websocket is not None and client.websocket is not websocket:
            logger.info(f"[SpeakerBrokerService] Ignoring stale unregister for client_id: {client_id} — id re-registered on a newer connection")
            return

        self._remove_client_from_speakers(client_id)
        self.control_clients.unregister(client_id)

    async def handle_assign_speaker(self, event: Event):
        payload = event.payload
        client_id = payload.get("client_id")
        speaker_name = payload.get("speaker_name")
        logger.info(f"[SpeakerBrokerService] Handling ASSIGN_SPEAKER event for client_id: {client_id} to speaker_name: {speaker_name}")
        if not client_id or not speaker_name:
            return
        
        self._remove_client_from_speakers(client_id)
        if client_id not in self.control_clients._clients:
            logger.warning(f"[SpeakerBrokerService] ASSIGN_SPEAKER for unknown client_id: {client_id} — ignoring")
            return
        speaker = self._assign_client_to_speaker(client_id, speaker_name)
        logger.info(f"[SpeakerBrokerService] Assigned client_id: {client_id} to speaker_name: {speaker_name} with result: {speaker is not False}")
        if speaker:
            self.control_clients._clients[client_id].speaker_name = speaker_name
            await self.broadcast_context_to_clients(speaker)

    async def handle_speaker_removed(self, removed_speaker):
        """Re-home clients attached to a speaker that was just removed from the
        config (live speaker management, Phase B): they move to the default
        speaker, or detach when no default exists."""
        if not removed_speaker:
            return
        orphans = list(removed_speaker.clients)
        if not orphans:
            return
        fallback = self.speakers.get_default_speaker()
        target = fallback if fallback and fallback is not removed_speaker else None
        for client_id in orphans:
            self._remove_client_from_speakers(client_id)
            client = self.control_clients._clients.get(client_id)
            if not client:
                continue
            if target:
                self._assign_client_to_speaker(client_id, target.speaker_name)
                client.speaker_name = target.speaker_name
            else:
                client.speaker_name = None
            logger.info(f"[SpeakerBrokerService] Re-homed client_id: {client_id} after speaker '{removed_speaker.speaker_name}' was removed")
        if target:
            await self.broadcast_context_to_clients(target)


    def _remove_client_from_speakers(self, client_id):
        result = False
        for speaker in self.speakers._speakers.values():
            if client_id in speaker.clients:
                speaker.clients.discard(client_id)
                result = True
        
        return result

    def _assign_client_to_speaker(self, client_id, speaker_name):
        speaker = self.speakers.get_speaker(speaker_name=speaker_name)
        if speaker:
            speaker.clients.add(client_id)
            return speaker
        return False

    def get_speaker_for_client(self, client_id):
        client = self.control_clients._clients.get(client_id)
        if not client:
            return None
        
        speaker_name = client.speaker_name
        speaker = self.speakers.get_speaker(speaker_name=speaker_name)
        if not speaker:
            return None
        
        return speaker

    async def broadcast_context_to_clients(self, speaker: Speaker):
        if not speaker:
            logger.warning(f"[SpeakerBrokerService]  No speaker provided for broadcasting message")
            return
        logger.info(f"[SpeakerBrokerService] Broadcasting message to speaker: {speaker.speaker_name} with clients: {speaker.clients}")
        for client_id in list(speaker.clients):
            client = self.control_clients._clients.get(client_id)
            if not client:
                logger.warning(f"[SpeakerBrokerService] Purging unknown client_id: {client_id} from speaker {speaker.speaker_name}")
                speaker.clients.discard(client_id)
                continue
            result_payload = self._get_mediaplayer_context_for_client(client)
            await client.send_callback({"type": "current_track", "payload": result_payload})

    async def broadcast_volume_to_clients(self, speaker: Speaker):
        if not speaker:
            logger.warning(f"[SpeakerBrokerService] No speaker provided for broadcasting message")
            return
        logger.info(f"[SpeakerBrokerService] Broadcasting volume message to speaker: {speaker.speaker_name} with clients: {speaker.clients}")
        volume_manager = speaker.mediaplayer.volume_manager
        payload = {
            "volume": volume_manager.volume,
            "muted": bool(getattr(volume_manager, "is_muted", False)),
        }
        for client_id in list(speaker.clients):
            client = self.control_clients._clients.get(client_id)

            if client:
                await client.send_callback({"type": "volume_changed", "payload": payload})


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
        client_id = payload.get("client_id")

        async def play_album_action(mediaplayer):
            result = await playback_service.load_from_album_id(
                album_id, 
                player=mediaplayer, 
                start_track_index=start_track_index
            )
            logger.info(f"[SpeakerBrokerService] Loaded album_id: {album_id} for client_id: {client_id} with result: {result}")

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
        async def set_volume_action(mediaplayer):
            result = await mediaplayer.set_volume(event)
            logger.info(f"[SpeakerBrokerService] Set volume to: {event.payload.get('volume')}")
        
        await self._execute_media_action(event, "set_volume", custom_action=set_volume_action)               

    async def handle_volume_mute(self, event: Event):
        await self._execute_media_action(event, "handle_volume_mute")    

    async def handle_toggle_repeat(self, event: Event):
        await self._execute_media_action(event, "toggle_repeat")                        

    async def handle_play_track(self, event: Event):
        async def play_track_action(mediaplayer):
            result = await mediaplayer.play_track(track_index=event.payload.get("track_index"))
            logger.info(f"[SpeakerBrokerService] Loaded track_index: {event.payload.get('track_index')}")
        
        await self._execute_media_action(event, "play_track", custom_action=play_track_action)  

    def resolve_speaker(self, client_id: str = None, device_name: str = None) -> Optional[Speaker]:
        """Resolve the speaker for a routing context, in priority order:
        1. The speaker the client is attached to (client_id)
        2. The speaker explicitly named in the payload (device_name)
        3. The configured default speaker
        Returns None (with a log line) when nothing can be resolved."""
        speaker = None
        if client_id:
            speaker = self.get_speaker_for_client(client_id)
            if speaker is None:
                logger.warning(f"[SpeakerBrokerService] client_id {client_id} not attached to a speaker — falling back")
        if speaker is None and device_name:
            speaker = self.speakers.get_speaker(speaker_name=device_name)
            if speaker is None:
                logger.warning(f"[SpeakerBrokerService] Unknown device_name '{device_name}' — falling back")
        if speaker is None:
            speaker = self.speakers.get_default_speaker()
            if speaker:
                logger.info(f"[SpeakerBrokerService] No client/device context — using default speaker {speaker.speaker_name}")
            else:
                logger.warning("[SpeakerBrokerService] Cannot resolve a speaker: no routing context and no speakers configured")
        return speaker

    async def _execute_media_action(self, event: Event, action_name: str, custom_action=None, broadcaster=None):
        payload = event.payload
        client_id = payload.get("client_id")
        logger.info(f"[SpeakerBrokerService] Executing media action: {action_name} for client_id: {client_id} with payload: {payload}")

        speaker = self.resolve_speaker(client_id=client_id, device_name=payload.get("device_name"))
        if speaker is None:
            return

        mediaplayer = speaker.mediaplayer
        if not mediaplayer:
            logger.warning(f"[SpeakerBrokerService] Speaker {speaker.speaker_name} has no media player instance")
            return

        if custom_action:
            await custom_action(mediaplayer)
        else:
            action_method = getattr(mediaplayer, action_name)
            await action_method()

        if broadcaster is None:
            await self.broadcast_context_to_clients(speaker)
        else:
            await broadcaster(speaker)