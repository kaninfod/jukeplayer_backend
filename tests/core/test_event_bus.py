import pytest
from unittest.mock import MagicMock, AsyncMock
from app.services.media_player_service.media_player_service import MediaPlayerService
from app.core import EventType
from app.core.event_bus import EventBus, Event

@pytest.mark.asyncio
async def test_handle_volume_up_emits_event(media_player_service, mock_event_bus):
    # Call the method
    await media_player_service.handle_volume_up()
    # Assert that emit was called at least once
    assert mock_event_bus.emit.called
    # Optionally, check the arguments of the first call
    event_arg = mock_event_bus.emit.call_args[0][0]
    assert event_arg.type == EventType.VOLUME_CHANGED
    assert isinstance(event_arg.payload, dict)



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