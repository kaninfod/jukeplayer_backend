# Device Switch Implementation Review & Migration Plan

## Current Implementation (Old Way)

### WebSocket Handler
```python
# app/websocket/mediaplayer_ws.py:400
async def handle_switch_device(self, payload):
    device = payload.get("device_id")
    backend = payload.get("device_backend")
    
    # Emit SWITCH_DEVICE event to service layer
    result = await event_bus.aemit(Event(
        type=EventType.SWITCH_DEVICE,
        payload={
            "device_id": device,
            "device_backend": backend,
            "client_id": self.registered_client_id or self.client_id
        }
    ))
    
    # Broadcast response to all clients
    result = await event_bus.aemit(Event(
        type=EventType.BROADCAST_GENERIC_MESSAGE,
        payload={
            "message_type": "switch_device_response",
            "message_payload": result
        }
    ))
```

### Backend Implementation
- Calls `player.switch_playback_backend(backend, device_name)`
- This **shuts down** the current playback backend
- **Reconnects** to the new device
- Disrupts playback if music was playing

**Problem**: Device switching is destructive - stops music, reconnects, loses state

## New Implementation (Device Instance Mapping)

### Architecture
- **One MediaPlayerService instance per physical device** - always running
- Each instance handles a single device (device_name is locked at initialization)
- **Client registry maps clients → device instances**
- Clients control a device by switching which instance they're connected to
- **No shutdown/reconnect** - just change the mapping

### Key Components

#### Client Registry Methods (already implemented)
```python
# app/services/client_registry.py

def set_client_active_instance(client_id: str, player_instance) -> None:
    """Client takes control of a specific MediaPlayerService instance.
    Multiple clients can control the same instance (shared control).
    """
    
def get_client_active_instance(client_id: str) -> Optional:
    """Which instance is this client currently controlling?"""
    
def get_or_create_player_instance(device_name: str) -> MediaPlayerService:
    """Get MediaPlayerService instance for device (creates if needed).
    Raises KeyError if device not in config.
    """
    
def get_configured_devices(self) -> List[str]:
    """Return list of all configured physical devices."""
```

## Proposed WebSocket Implementation

### New handle_switch_device
```python
async def handle_switch_device(self, payload):
    """Switch client to control a different device.
    
    Does NOT restart playback. Just changes which MediaPlayerService 
    instance this client controls. Future commands go to that device.
    
    Args:
        payload: {"device_id": "kitchen"} or {"device_id": "bedroom"}
    """
    try:
        device_id = payload.get("device_id")
        
        if not device_id:
            raise ValueError("Missing device_id in payload")
        
        client_registry = get_service("client_registry")
        
        # Get the MediaPlayerService instance for this device
        # Raises KeyError if device not configured
        try:
            player_instance = client_registry.get_or_create_player_instance(device_id)
        except KeyError as e:
            # List available devices for error message
            available = client_registry.get_configured_devices()
            raise ValueError(
                f"Device '{device_id}' not configured. "
                f"Available devices: {', '.join(available) if available else 'None'}"
            )
        
        # Map this client to the new device instance
        client_registry.set_client_active_instance(
            self.registered_client_id or self.client_id,
            player_instance
        )
        
        # Get current state of the new device
        device_state = player_instance.get_context()
        
        # Send success response with new device state
        await self.send_message({
            "type": "switch_device_response",
            "payload": {
                "status": "success",
                "message": f"Switched to device '{device_id}'",
                "device_id": device_id,
                "current_state": device_state
            }
        })
        
        logger.info(
            f"Client {self.client_id} switched to device '{device_id}' | "
            f"Active clients on {device_id}: "
            f"{client_registry.get_instance_active_clients(device_id)}"
        )
        
    except ValueError as e:
        await self.send_message({
            "type": "switch_device_response",
            "payload": {
                "status": "error",
                "message": str(e)
            }
        })
        logger.warning(f"Device switch failed: {e}")
    except Exception as e:
        await self.send_message({
            "type": "switch_device_response",
            "payload": {
                "status": "error",
                "message": f"Unexpected error: {str(e)}"
            }
        })
        logger.error(f"Error handling switch_device: {e}", exc_info=True)
```

## Key Differences

### Old Way (Current)
| Aspect | Details |
|--------|---------|
| **Action** | Emit SWITCH_DEVICE event → service layer shuts down backend and reconnects |
| **Side Effects** | Stops playback, loses connection, reconnects |
| **Timing** | Slow (disconnect/reconnect cycle) |
| **State Loss** | Resets backend, reconnects |
| **Scope** | Global (affects all clients) |

### New Way (Proposed)
| Aspect | Details |
|--------|---------|
| **Action** | Get player_instance for device → map client to instance |
| **Side Effects** | None - just changes routing |
| **Timing** | Instant (simple map update) |
| **State Loss** | None - device keeps running |
| **Scope** | Per-client (doesn't affect other clients) |

## Benefits of New Implementation

1. **Non-destructive** - No playback interruption
2. **Per-client device control** - Client A controls kitchen, Client B controls bedroom simultaneously
3. **Faster** - No reconnection delay
4. **Scalable** - Works with arbitrary number of devices (all always running)
5. **Consistent with other controls** - Follows same per-client routing pattern as volume/track updates
6. **Simple** - 3 lines of code in handler, no event bus involvement

## Implementation Steps

1. **Replace handle_switch_device** in `app/websocket/mediaplayer_ws.py`
   - Remove event_bus.aemit(EventType.SWITCH_DEVICE)
   - Add direct client_registry.set_client_active_instance()
   - Send success/error response directly to client

2. **No backend changes needed**
   - Client registry already has all methods
   - Device instances already running
   - PlaybackService already routes via _get_player_instance_for_event()

3. **Remove dead code** (optional)
   - SWITCH_DEVICE event handler in PlaybackService (no longer emitted)
   - EventType.SWITCH_DEVICE enum value (no longer used)

4. **Test scenarios**
   - Two clients, one device: Both switch to different devices independently ✓
   - Track changes only affect current device ✓
   - Volume changes only affect current device ✓
   - Mute state per-device ✓
   - All events broadcast to correct client's current device ✓

## API Contract Changes

### Request (unchanged)
```json
{
  "type": "switch_device",
  "payload": {
    "device_id": "kitchen"
  }
}
```

### Response (improved)
```json
{
  "type": "switch_device_response",
  "payload": {
    "status": "success",
    "message": "Switched to device 'kitchen'",
    "device_id": "kitchen",
    "current_state": {
      "status": "playing",
      "volume": 50,
      "current_track": {...}
    }
  }
}
```

Or on error:
```json
{
  "type": "switch_device_response",
  "payload": {
    "status": "error",
    "message": "Device 'bedroom' not configured. Available devices: kitchen, living_room"
  }
}
```

## Questions for Review

1. ✅ Should device state be returned in response? (Yes, helps client UI update immediately)
2. ✅ Should we broadcast to all clients when one switches? (No - per-client, not global)
3. ✅ Should switching fail if device has no active instance? (No - get_or_create_player_instance handles it)
4. ✅ Should we restrict device switching to specific client types? (Current: no restrictions, design is client-agnostic)
