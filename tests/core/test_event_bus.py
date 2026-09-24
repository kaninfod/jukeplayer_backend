import pytest
import asyncio
import threading
from unittest.mock import MagicMock, AsyncMock
from app.services import MediaPlayerService
from app.core import EventType, Event
from app.core.event_bus import EventBus

@pytest.fixture
def mock_event_bus():
    return MagicMock(spec=EventBus)

@pytest.mark.asyncio
async def test_handle_volume_up_pushes_backend_volume(media_player_service, mock_playback_backend):
    # Volume changes are delivered to clients by the broker broadcast, not by
    # a dead event emit — assert the backend received the new volume instead.
    result = await media_player_service.handle_volume_up()
    assert result["message"] == "Volume increased"
    mock_playback_backend.set_volume.assert_called()



def test_eventbus_emit_calls_handler():
    bus = EventBus()
    received = {}

    def handler(event):
        received['event'] = event

    bus.subscribe('my_event', handler)
    event = Event('my_event', {'foo': 'bar'})
    bus.emit(event)  # If emit is async, use await bus.aemit(event)

    assert 'event' in received
    assert received['event'].type == 'my_event'
    assert received['event'].payload == {'foo': 'bar'}    


@pytest.mark.asyncio
async def test_eventbus_aemit_calls_handler():
    bus = EventBus()
    received = {}

    def handler(event):
        received['event'] = event

    bus.subscribe('my_event', handler)
    event = Event('my_event', {'foo': 'bar'})
    await bus.aemit(event)  # If emit is async, use await bus.aemit(event)

    assert 'event' in received
    assert received['event'].type == 'my_event'
    assert received['event'].payload == {'foo': 'bar'}        


@pytest.mark.asyncio
async def test_emit_from_foreign_thread_runs_on_main_loop():
    """Handlers emitted from a foreign thread (pychromecast callback thread)
    must run on the captured main loop, not on a fresh asyncio.run() loop."""
    bus = EventBus()
    bus.set_main_loop(asyncio.get_running_loop())

    done = asyncio.Event()
    received = {}

    async def handler(event):
        received['event'] = event
        done.set()

    bus.subscribe(EventType.STOP, handler)

    thread = threading.Thread(target=lambda: bus.emit(Event(EventType.STOP, {})))
    thread.start()
    thread.join()

    await asyncio.wait_for(done.wait(), timeout=2)
    assert received['event'].type == EventType.STOP


@pytest.mark.asyncio
async def test_emit_without_main_loop_does_not_raise():
    """Without set_main_loop (or before startup), async handlers are dropped
    with an error log — emit must still be safe to call."""
    bus = EventBus()

    async def handler(event):
        raise AssertionError("handler must not run without a main loop")

    bus.subscribe(EventType.STOP, handler)
    bus.emit(Event(EventType.STOP, {}))  # must not raise