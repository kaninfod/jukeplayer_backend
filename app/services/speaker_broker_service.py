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
            return {"ok": False, "error": "ASSIGN_SPEAKER needs both client_id and speaker_name"}

        self._remove_client_from_speakers(client_id)
        if client_id not in self.control_clients._clients:
            logger.warning(f"[SpeakerBrokerService] ASSIGN_SPEAKER for unknown client_id: {client_id} — ignoring")
            return {"ok": False, "error": f"Unknown client_id '{client_id}'"}
        speaker = self._assign_client_to_speaker(client_id, speaker_name)
        if speaker:
            # store the canonical registry name, not the payload's display form
            self.control_clients._clients[client_id].speaker_name = speaker.speaker_name
            await self.broadcast_context_to_clients(speaker)
            return {"ok": True, "speaker": speaker.speaker_name,
                    "message": f"Client '{client_id}' assigned to '{speaker.speaker_name}'"}
        return {"ok": False, "error": f"Unknown speaker '{speaker_name}'"}

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
        # Clients may remember speaker names in display form ('OPENRUN PRO 2
        # BY SHOKZ') — normalize before the lookup (registry keys are store
        # names). Same normalization as resolve_speaker (bug found 2026-09-24).
        from app.services.speaker_manager_service import normalize_speaker_name
        speaker = self.speakers.get_speaker(speaker_name=normalize_speaker_name(speaker_name))
        if speaker:
            speaker.clients.add(client_id)
            return speaker
        return False

    def get_speaker_for_client(self, client_id):
        client = self.control_clients._clients.get(client_id)
        if not client:
            return None

        speaker_name = client.speaker_name
        if not speaker_name:
            return None
        # client.speaker_name may be a stale display-form name from before the
        # canonical-name fix — normalize on every lookup
        from app.services.speaker_manager_service import normalize_speaker_name
        speaker = self.speakers.get_speaker(speaker_name=normalize_speaker_name(speaker_name))
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
            if not result:
                return {"ok": False, "error": f"Could not load album '{album_id}'"}
            return {"message": f"Album '{album_id}' queued (starting at track {start_track_index})"}

        # Pass it to the helper
        return await self._execute_media_action(event, "play_album", custom_action=play_album_action)

    async def handle_play_pause(self, event: Event):
        return await self._execute_media_action(event, "play_pause")

    async def handle_next_track(self, event: Event):
        async def next_action(mediaplayer):
            # the HTTP route marks manual next_track as forced; auto-advance
            # (TRACK_FINISHED) shares this handler without the flag
            force = bool(event.payload.get("force"))
            result = await mediaplayer.next_track(force=force)
            if result is False:
                return {"message": "End of playlist — playback stopped"}

        return await self._execute_media_action(event, "next_track", custom_action=next_action)

    async def handle_previous_track(self, event: Event):
        return await self._execute_media_action(event, "previous_track")

    async def handle_stop(self, event: Event):
        return await self._execute_media_action(event, "stop")

    async def handle_volume_up(self, event: Event):
        return await self._execute_media_action(event, "handle_volume_up", broadcaster=self.broadcast_volume_to_clients)

    async def handle_volume_down(self, event: Event):
        return await self._execute_media_action(event, "handle_volume_down", broadcaster=self.broadcast_volume_to_clients)

    async def handle_set_volume(self, event: Event):
        async def set_volume_action(mediaplayer):
            await mediaplayer.set_volume(event)
            logger.info(f"[SpeakerBrokerService] Set volume to: {event.payload.get('volume')}")

        return await self._execute_media_action(event, "set_volume", custom_action=set_volume_action)

    async def handle_volume_mute(self, event: Event):
        return await self._execute_media_action(event, "handle_volume_mute")

    async def handle_toggle_repeat(self, event: Event):
        return await self._execute_media_action(event, "toggle_repeat")

    async def handle_play_track(self, event: Event):
        async def play_track_action(mediaplayer):
            await mediaplayer.play_track(track_index=event.payload.get("track_index"))
            logger.info(f"[SpeakerBrokerService] Loaded track_index: {event.payload.get('track_index')}")

        return await self._execute_media_action(event, "play_track", custom_action=play_track_action)

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
            # Event payloads carry display-form names (mpv uppercases and uses
            # spaces: 'OPENRUN PRO 2 BY SHOKZ') while registry keys are the
            # normalized store names ('openrun_pro_2_by_shokz') — normalize
            # before the lookup, else live-added mpv speakers fall through to
            # the default speaker (routing bug found 2026-09-24: next_track
            # after track-end executed against the wrong speaker).
            from app.services.speaker_manager_service import normalize_speaker_name
            speaker = self.speakers.get_speaker(speaker_name=normalize_speaker_name(device_name))
            if speaker is None:
                logger.warning(f"[SpeakerBrokerService] Unknown device_name '{device_name}' — falling back")
        if speaker is None:
            speaker = self.speakers.get_default_speaker()
            if speaker:
                logger.info(f"[SpeakerBrokerService] No client/device context — using default speaker {speaker.speaker_name}")
            else:
                logger.warning("[SpeakerBrokerService] Cannot resolve a speaker: no routing context and no speakers configured")
        return speaker

    async def _execute_media_action(self, event: Event, action_name: str, custom_action=None, broadcaster=None) -> dict:
        """Execute one media action on the resolved speaker and broadcast the
        new context to its clients.

        Returns a structured result the HTTP routes can wrap uniformly:
        {"ok": True, "speaker": name, "volume": …, "muted": …,
         "repeat_album": …} on success, or {"ok": False, "error": …} on
        failure — no more implicit-None results that routes misread."""
        payload = event.payload
        client_id = payload.get("client_id")
        logger.info(f"[SpeakerBrokerService] Executing media action: {action_name} for client_id: {client_id} with payload: {payload}")

        speaker = self.resolve_speaker(client_id=client_id, device_name=payload.get("device_name"))
        if speaker is None:
            return {"ok": False,
                    "error": "No speaker could be resolved (no routing context and no speakers configured)"}

        mediaplayer = speaker.mediaplayer
        if not mediaplayer:
            logger.warning(f"[SpeakerBrokerService] Speaker {speaker.speaker_name} has no media player instance")
            return {"ok": False, "speaker": speaker.speaker_name,
                    "error": f"Speaker '{speaker.speaker_name}' has no media player instance"}

        if custom_action:
            detail = await custom_action(mediaplayer) or {}
        else:
            action_method = getattr(mediaplayer, action_name)
            detail = await action_method() or {}

        if broadcaster is None:
            await self.broadcast_context_to_clients(speaker)
        else:
            await broadcaster(speaker)

        # Post-action state snapshot: one shape for every action, so routes
        # never guess result[0] shapes again. Detail (if the custom action
        # returned one) is merged last.
        context = mediaplayer.get_context()
        result = {
            "ok": True,
            "speaker": speaker.speaker_name,
            "volume": context.get("volume"),
            "muted": context.get("muted"),
            "repeat_album": context.get("repeat_album"),
            "message": action_name,
        }
        if isinstance(detail, dict):
            result.update(detail)
        return result