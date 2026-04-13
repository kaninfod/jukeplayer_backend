"""
Centralized WebSocket event dispatcher.

This module sets up a single event handler for each event type that broadcasts 
to all connected WebSocket clients via the client_registry. This prevents handler 
duplication that occurs when each connection subscribes its own handlers.

Key advantages:
- ONE handler per event type (constant overhead)
- Scales linearly with number of events, not connections
- Clean separation between service layer and websocket layer
- Easier to debug and understand event flow
"""

import asyncio
import logging
import threading
from typing import Dict, Optional
from app.core import EventType, Event
from app.core.event_bus import event_bus
from app.core.service_container import get_service

logger = logging.getLogger(__name__)


class WebSocketEventDispatcher:
    """Manages centralized event dispatch to WebSocket clients."""
    
    def __init__(self):
        """Initialize dispatcher (handlers not yet registered)."""
        self._topic_data_fetchers: Dict[EventType, callable] = {}
        self._dispatch_handlers_registered = False
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
    
    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        """Set the main event loop for scheduling async tasks."""
        self._event_loop = loop
    
    def register_topic_fetcher(self, event_type: EventType, fetcher: callable):
        """
        Register a data fetcher for an event topic.
        
        Args:
            event_type: The event type to fetch data for
            fetcher: Callable that returns current data for this event type
        """
        self._topic_data_fetchers[event_type] = fetcher
        logger.info(f"Registered data fetcher for {event_type}")
    
    def setup_dispatch_handlers(self):
        """Setup centralized event dispatch handlers."""
        if self._dispatch_handlers_registered:
            logger.warning("Dispatch handlers already registered")
            return
        
        # Create and register handlers for each event type
        event_bus.subscribe(EventType.TRACK_CHANGED, self.handle_track_changed) #self._setup_track_changed_handler()
        event_bus.subscribe(EventType.VOLUME_CHANGED, self.handle_volume_changed) #self._setup_volume_changed_handler()
        event_bus.subscribe(EventType.NOTIFICATION, self.handle_notification) #self._setup_notification_handler()
        event_bus.subscribe(EventType.TOGGLE_REPEAT_CHANGED, self.handle_toggle_repeat_changed)
        

        self._dispatch_handlers_registered = True
        logger.info("WebSocket event dispatch handlers registered (3 total)")
    
    def _schedule_broadcast(self, coro):
        """Schedule an async broadcast coroutine to run in the event loop."""
        if self._event_loop is None:
            logger.warning("Event loop not set, cannot broadcast")
            return
        
        try:
            asyncio.run_coroutine_threadsafe(coro, self._event_loop)
        except Exception as e:
            logger.error(f"Failed to schedule broadcast: {e}")
    
    # def _setup_track_changed_handler(self):
    #     """Setup TRACK_CHANGED event handler."""
    #     event_bus.subscribe(EventType.TRACK_CHANGED, self.handle_track_changed)

    def handle_track_changed(self, event: Event):
        """Broadcast track change to all connected clients, shaping payload per client capabilities."""
        self._schedule_broadcast(self._broadcast_track_changed())

    async def _broadcast_track_changed(self):
        try:
            client_registry = get_service("client_registry")
            media_player_service = get_service("media_player_service")
            count = 0
            for client in getattr(client_registry, '_clients', {}).values():
                try:
                    if "minimal_messaging" in getattr(client, 'capabilities', []):
                        shaped_payload = media_player_service.get_context(minimal=True)
                    else:
                        shaped_payload = media_player_service.get_context()
                    message = {"type": "current_track", "payload": shaped_payload}
                    await client.send_message(message)
                    count += 1
                except Exception as e:
                    logger.error(f"Failed to send current_track to client {getattr(client, 'client_id', '?')}: {e}")
            logger.info(f"Broadcasted current_track to {count} clients (per-client shaping)")
        except Exception as e:
            logger.error(f"Error broadcasting track_changed: {e}")

    def handle_volume_changed(self, event: Event):
        """Broadcast volume change to all connected clients."""
        self._schedule_broadcast(self._broadcast_volume_changed(event))

    async def _broadcast_volume_changed(self, event: Event):
        try:
            client_registry = get_service("client_registry")
            # If we have a fetcher, use fresh data; otherwise use event payload
            if EventType.VOLUME_CHANGED in self._topic_data_fetchers:
                try:
                    payload = self._topic_data_fetchers[EventType.VOLUME_CHANGED]()
                except Exception as e:
                    logger.error(f"Error fetching volume data: {e}")
                    payload = event.payload
            else:
                payload = event.payload

            message = {"type": "volume_changed", "payload": payload}
            
            await client_registry.broadcast_to_all(message)
        except Exception as e:
            logger.error(f"Error broadcasting volume_changed: {e}")

    def handle_toggle_repeat_changed(self, event: Event):
        """Broadcast toggle repeat change to all connected clients."""
        self._schedule_broadcast(self._broadcast_toggle_repeat_changed(event))

    async def _broadcast_toggle_repeat_changed(self, event: Event):
        try:
            client_registry = get_service("client_registry")
            payload = event.payload if event else {}
            logger.info(f"Broadcasting toggle_repeat_changed with payload: {payload}")
            message = {"type": "toggle_repeat_changed", "payload": payload}
            await client_registry.broadcast_to_all(message)
        except Exception as e:
            logger.error(f"Error broadcasting toggle_repeat_changed: {e}")


    def handle_notification(self, event: Event):
        """Broadcast notification to all connected clients."""
        self._schedule_broadcast(self._broadcast_notification(event))

    async def _broadcast_notification(self, event: Event):
        try:
            client_registry = get_service("client_registry")
            payload = event.payload if event else {}
            message = {"type": "notification", "payload": payload}
            await client_registry.broadcast_to_all(message)
        except Exception as e:
            logger.error(f"Error broadcasting notification: {e}")


# Global dispatcher instance
_dispatcher: Optional[WebSocketEventDispatcher] = None


def get_dispatcher() -> WebSocketEventDispatcher:
    """Get the global event dispatcher (creating if needed)."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = WebSocketEventDispatcher()
    return _dispatcher


def setup_websocket_dispatcher(track_fetcher: callable, volume_fetcher: callable, event_loop: asyncio.AbstractEventLoop = None):
    """
    Initialize the WebSocket event dispatcher with data fetchers.
    
    Call this once during application startup. The dispatcher will automatically
    use asyncio.run_coroutine_threadsafe to schedule broadcasts in the provided
    event loop.
    
    Args:
        track_fetcher: Callable that returns current track data
        volume_fetcher: Callable that returns current volume data
        event_loop: The asyncio event loop to use for scheduling broadcasts.
                   If None, will attempt to get the current running loop.
    """
    dispatcher = get_dispatcher()
    
    # Set the event loop
    if event_loop is None:
        try:
            event_loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("No running event loop found, dispatcher may not be able to broadcast")
    
    if event_loop:
        dispatcher.set_event_loop(event_loop)
    
    dispatcher.register_topic_fetcher(EventType.TRACK_CHANGED, track_fetcher)
    dispatcher.register_topic_fetcher(EventType.VOLUME_CHANGED, volume_fetcher)
    dispatcher.setup_dispatch_handlers()
    logger.info("WebSocket dispatcher initialized")
