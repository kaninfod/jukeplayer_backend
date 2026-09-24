import threading
import logging
import asyncio
import inspect
from collections import defaultdict

logger = logging.getLogger(__name__)

class Event:
    def __init__(self, type, payload=None):
        self.type = type
        self.payload = payload or {}

class EventBus:
    def __init__(self):
        self._handlers = defaultdict(list)  # EventType -> [handler_fn]
        self._lock = threading.Lock()
        self._main_loop: "asyncio.AbstractEventLoop | None" = None

    def set_main_loop(self, loop) -> None:
        """Remember the app's main event loop so handlers emitted from foreign
        threads (e.g. pychromecast's socket thread) run on the right loop."""
        self._main_loop = loop

    def subscribe(self, event_type, handler):
        with self._lock:
            # Prevent duplicate subscriptions
            if handler not in self._handlers[event_type]:
                #logger.info(f"Subscribing handler {handler.__name__} to event type {event_type}")
                self._handlers[event_type].append(handler)
            else:
                logger.debug(f"Handler {handler.__name__} already subscribed to {event_type} - skipping duplicate")

    def unsubscribe(self, event_type, handler):
        handlers = self._handlers.get(event_type, [])
        try:
            handlers.remove(handler)
            logger.info(f"Unsubscribed handler {handler.__name__} from event type {event_type}")
            return True
        except ValueError:
            return False

    async def aemit(self, event: Event):
        '''Async version of emit. Use this inside async functions.'''
        results = []
        handlers = self._handlers.get(event.type, [])
        if not handlers:
            logger.debug(f"No handlers registered for event type: {event.type}")
        else:
            logger.info(f"Broadcasting event {event.type} to {len(handlers)} handler(s) [async]")
            for handler in handlers:
                logger.debug(f"Calling handler {handler.__name__} for event type {event.type}")
                try:
                    if inspect.iscoroutinefunction(handler):
                        result = await handler(event)
                    else:
                        result = handler(event)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Handler {handler.__name__} failed for event type {event.type}: {e}", exc_info=True)
        return results

    def emit(self, event: Event):
        """Fire an event from anywhere (any thread). Async handlers are always
        scheduled on the captured main loop — never via asyncio.run(), which
        created a fresh event loop per event and raced loop-bound primitives
        (locks, asyncio.Events, websocket sends)."""
        results = []
        handlers = self._handlers.get(event.type, [])
        if not handlers:
            logger.debug(f"No handlers registered for event type: {event.type}")
            return results

        logger.info(f"Broadcasting event {event.type} to {len(handlers)} handler(s)")
        for handler in handlers:
            logger.debug(f"Calling handler {handler.__name__} for event type {event.type}")
            try:
                if inspect.iscoroutinefunction(handler):
                    try:
                        loop = asyncio.get_running_loop()
                        # Already async context: background task in this loop
                        loop.create_task(handler(event))
                        results.append(True)
                    except RuntimeError:
                        # Foreign thread (e.g. pychromecast/MPV callback thread)
                        if self._main_loop and self._main_loop.is_running():
                            self._main_loop.call_soon_threadsafe(
                                self._main_loop.create_task, handler(event))
                            results.append(True)
                        else:
                            logger.error(
                                f"Cannot schedule async handler {handler.__name__} for {event.type}: "
                                f"no main event loop captured (call set_main_loop at startup)")
                else:
                    result = handler(event)
                    results.append(result)
            except Exception as e:
                logger.error(f"Handler {handler.__name__} failed for event type {event.type}: {e}", exc_info=True)
        return results

# Singleton instance for the app
event_bus = EventBus()
