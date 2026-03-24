import threading
import logging
from collections import defaultdict

logger = logging.getLogger("core.event_bus")

class Event:
    def __init__(self, type, payload=None):
        self.type = type
        self.payload = payload or {}

class EventBus:
    def __init__(self):
        self._handlers = defaultdict(list)  # EventType -> [handler_fn]
        self._lock = threading.Lock()

    def subscribe(self, event_type, handler):
        with self._lock:
            # Prevent duplicate subscriptions
            if handler not in self._handlers[event_type]:
                logger.info(f"Subscribing handler {handler.__name__} to event type {event_type}")
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

    def emit(self, event: Event):
        results = []

        handlers = self._handlers.get(event.type, [])
        if not handlers:
            logger.debug(f"No handlers registered for event type: {event.type}")
        else:
            logger.info(f"Broadcasting event {event.type} to {len(handlers)} handler(s)")
            for handler in handlers:
                logger.debug(f"Calling handler {handler.__name__} for event type {event.type}")
                try:
                    result = handler(event)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Handler {handler.__name__} failed for event type {event.type}: {e}")
        return results

# Singleton instance for the app
event_bus = EventBus()
