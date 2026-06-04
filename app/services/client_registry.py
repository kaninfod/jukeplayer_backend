"""
Client Registry Service
Tracks connected hardware clients (RPi, ESP32, etc.) and their capabilities.
Manages persistent client connections and event broadcasting.
"""

import asyncio
import logging
import uuid
from typing import Dict, List, Optional, Callable, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Session reconnection timeout: allow client to reconnect within this window
# Reconnections within timeout reuse the same client_id and device mapping
RECONNECTION_TIMEOUT = timedelta(minutes=5)


class ClientInfo:
    """Information about a connected client."""
    
    def __init__(self, client_id: str, client_type: str, user_name: str, 
                 capabilities: List[str], connected_at: datetime, client_ip: Optional[str] = None, 
                 websocket=None, send_callback: Optional[Callable] = None, session_token: Optional[str] = None):
        """
        Args:
            client_id: System-generated UUID for this client
            client_type: Type of client ('rpi', 'esp32', 'web', etc.)
            user_name: User-defined name from client config
            capabilities: List of capabilities (e.g., ['nfc_reader', 'display'])
            connected_at: Timestamp when client connected
            client_ip: IP address of the client (used to identify same physical device for hardware clients)
            websocket: Reference to the WebSocket connection (if applicable)
            send_callback: Async function to send messages to this client
            session_token: Unique session token for web clients (prevents IP-based deduplication)
        """
        self.client_id = client_id
        self.client_type = client_type
        self.user_name = user_name
        self.capabilities = capabilities
        self.connected_at = connected_at
        self.client_ip = client_ip
        self.websocket = websocket
        self.send_callback = send_callback
        self.session_token = session_token
    
    def to_dict(self):
        """Serialize to dictionary for API responses."""
        return {
            "client_id": self.client_id,
            "client_type": self.client_type,
            "user_name": self.user_name,
            "capabilities": self.capabilities,
            "client_ip": self.client_ip,
            "connected_at": self.connected_at.isoformat(),
        }
    
    async def send_message(self, message: Dict) -> bool:
        """
        Send a message to this client.
        
        Args:
            message: Message dict to send
            
        Returns:
            True if sent successfully, False if failed
        """
        if not self.send_callback:
            return False
        try:
            return await self.send_callback(message)
        except Exception as e:
            logger.error(f"Failed to send message to client {self.client_id}: {e}")
            return False


class ClientRegistry:
    """
    Registry of connected clients.
    Allows querying available hardware and directing requests to specific clients.
    Automatically handles reconnections from the same device by IP address.
    """
    
    def __init__(self):
        # Storage: client_id -> ClientInfo
        self._clients: Dict[str, ClientInfo] = {}
        # Also support lookup by user_name for convenience
        self._by_name: Dict[str, List[str]] = {}  # user_name -> [client_id1, client_id2, ...]
        # Track by IP to detect same physical device reconnecting (hardware clients only)
        self._by_ip: Dict[str, str] = {}  # ip_address -> client_id
        # Track by session token for web clients (prevents IP-based deduplication)
        self._by_session_token: Dict[str, str] = {}  # session_token -> client_id
        # Track disconnected sessions for recovery: session_token -> (client_id, disconnected_at)
        # Allows recognizing returning clients within RECONNECTION_TIMEOUT window
        self._disconnected_sessions: Dict[str, Tuple[str, datetime]] = {}
    
    def register(self, client_type: str, user_name: str, capabilities: List[str], 
                 client_ip: Optional[str] = None, websocket=None, send_callback: Optional[Callable] = None,
                 client_id: Optional[str] = None) -> ClientInfo:
        """
        Register a connected client.
        
        Smart client_id handling:
        - If client_id provided: Check if reconnecting (within timeout window)
          - Within timeout: Reuse client_id (recover device mapping + session state)
          - After timeout: Treat as new session
        - If client_id not provided: Generate new UUID
        
        This supports:
        - Web browsers: Generate UUID on first load, reuse on page refresh
        - Hardware clients: Hardcode their own client_id (e.g., "esp32-bedroom", "ha-instance-1")
        - HomeAssistant: Can provide fixed client_id for persistent sessions
        
        Args:
            client_type: Type of client ('web', 'rpi', 'esp32', 'homeassistant', etc.)
            user_name: User-defined name from client config
            capabilities: List of capabilities (e.g., ['nfc_reader', 'display'])
            client_ip: IP address of the client (informational)
            websocket: Optional WebSocket connection reference
            send_callback: Optional async function(message) to send messages to this client
            client_id: Optional client_id. If not provided, a new UUID will be generated.
                      For reconnections, provide the previous client_id.
            
        Returns:
            ClientInfo object with the assigned client_id (either reused or newly generated)
        """
        # Determine the client_id to use
        assigned_client_id = None
        session_recovered = False
        
        if client_id:
            # Client provided an ID (reconnect or hardcoded)
            
            # Check if currently connected with this client_id
            if client_id in self._clients:
                # Already connected - unregister old connection first
                old_client_info = self._clients[client_id]
                logger.info(
                    f"Client {client_id} reconnected while still connected. "
                    f"Unregistering old connection first."
                )
                self.unregister(client_id)
                assigned_client_id = client_id
                session_recovered = True
            
            # Check if in recovery window (recently disconnected)
            elif client_id in self._disconnected_sessions:
                old_client_id_stored, disconnected_at = self._disconnected_sessions[client_id]
                elapsed = datetime.now() - disconnected_at
                
                if elapsed < RECONNECTION_TIMEOUT:
                    # Within recovery window - reuse this client_id
                    logger.info(
                        f"Client {client_id} reconnected within recovery window ({elapsed.total_seconds():.1f}s). "
                        f"Recovering session and device mapping."
                    )
                    assigned_client_id = client_id
                    session_recovered = True
                    # Remove from disconnected sessions
                    del self._disconnected_sessions[client_id]
                else:
                    # Recovery window expired - treat as new session
                    logger.info(
                        f"Client {client_id} recovery window expired ({elapsed.total_seconds():.1f}s > "
                        f"{RECONNECTION_TIMEOUT.total_seconds():.0f}s). Starting fresh session."
                    )
                    del self._disconnected_sessions[client_id]
                    assigned_client_id = client_id  # Still use the provided ID
            else:
                # New client providing their own ID (hardware devices, HA, etc.)
                logger.info(f"New client with hardcoded ID: {client_id}")
                assigned_client_id = client_id
        
        # No client_id provided - generate new UUID (typically for web browsers on first load)
        if not assigned_client_id:
            assigned_client_id = str(uuid.uuid4())
            logger.info(f"Generated new client_id: {assigned_client_id}")
        
        now = datetime.now()
        
        client_info = ClientInfo(
            client_id=assigned_client_id,
            client_type=client_type,
            user_name=user_name,
            capabilities=capabilities,
            connected_at=now,
            client_ip=client_ip,
            websocket=websocket,
            send_callback=send_callback,
            session_token=assigned_client_id  # Use client_id as session identifier
        )
        
        self._clients[assigned_client_id] = client_info
        
        # Track by name for collision handling
        if user_name not in self._by_name:
            self._by_name[user_name] = []
        self._by_name[user_name].append(assigned_client_id)
        
        # Track by IP (informational only)
        if client_ip:
            self._by_ip[client_ip] = assigned_client_id
        
        # Track by session (use client_id directly)
        self._by_session_token[assigned_client_id] = assigned_client_id
        
        logger.info(
            f"Client registered: {user_name} (ID: {assigned_client_id}, Type: {client_type}, "
            f"IP: {client_ip}, Capabilities: {capabilities}, Recovered: {session_recovered})"
        )
        
        return client_info
    
    def unregister(self, client_id: str) -> Optional[ClientInfo]:
        """
        Unregister a client.
        
        Args:
            client_id: The client ID to unregister
            
        Returns:
            The unregistered ClientInfo, or None if not found
        """
        if client_id not in self._clients:
            return None
        
        client_info = self._clients.pop(client_id)
        
        # Remove from name index
        user_name = client_info.user_name
        if user_name in self._by_name:
            self._by_name[user_name].remove(client_id)
            if not self._by_name[user_name]:  # No more clients with this name
                del self._by_name[user_name]
        
        # Remove from IP index
        if client_info.client_ip in self._by_ip:
            del self._by_ip[client_info.client_ip]
        
        # For web clients: soft-delete session token (allow reconnection recovery)
        # Move to disconnected_sessions so we can recognize the returning client
        if client_info.session_token and client_info.client_type == "web":
            # Remove from active index
            if client_info.session_token in self._by_session_token:
                del self._by_session_token[client_info.session_token]
            # Add to disconnected sessions for recovery window
            self._disconnected_sessions[client_info.session_token] = (client_id, datetime.now())
            logger.info(
                f"Web client session marked for recovery: "
                f"session={client_info.session_token[:8]}..., "
                f"client_id={client_id} (will remain available for {RECONNECTION_TIMEOUT.total_seconds():.0f}s)"
            )
        # For hardware clients: hard-delete session token (no recovery)
        elif client_info.session_token and client_info.session_token in self._by_session_token:
            del self._by_session_token[client_info.session_token]
        
        logger.info(f"Client unregistered: {client_info.user_name} (ID: {client_id})")
        
        return client_info
    
    def get_by_id(self, client_id: str) -> Optional[ClientInfo]:
        """Get a client by its system ID."""
        return self._clients.get(client_id)
    
    def get_by_name(self, user_name: str) -> List[ClientInfo]:
        """Get all clients with a given user-defined name."""
        client_ids = self._by_name.get(user_name, [])
        return [self._clients[cid] for cid in client_ids if cid in self._clients]
    
    def get_by_ip(self, client_ip: str) -> Optional[ClientInfo]:
        """Get a client by its IP address."""
        client_id = self._by_ip.get(client_ip)
        if client_id:
            return self._clients.get(client_id)
        return None
    
    def get_by_session_token(self, session_token: str) -> Optional[ClientInfo]:
        """Get a client by its session token (web clients only)."""
        client_id = self._by_session_token.get(session_token)
        if client_id:
            return self._clients.get(client_id)
        return None
    
    def get_all(self) -> List[ClientInfo]:
        """Get all connected clients."""
        return list(self._clients.values())
    
    def get_by_capability(self, capability: str) -> List[ClientInfo]:
        """Get all clients with a specific capability."""
        return [c for c in self._clients.values() if capability in c.capabilities]
    
    def count(self) -> int:
        """Get total number of connected clients."""
        return len(self._clients)
    
    def cleanup_stale_sessions(self) -> int:
        """
        Remove stale disconnected sessions that have exceeded the reconnection timeout.
        
        Returns:
            Number of sessions cleaned up
        """
        now = datetime.now()
        stale_sessions = []
        
        for session_token, (client_id, disconnected_at) in self._disconnected_sessions.items():
            elapsed = now - disconnected_at
            if elapsed >= RECONNECTION_TIMEOUT:
                stale_sessions.append(session_token)
        
        for session_token in stale_sessions:
            client_id, disconnected_at = self._disconnected_sessions.pop(session_token)
            elapsed = (now - disconnected_at).total_seconds()
            logger.info(
                f"Cleaned up stale session: session={session_token[:8]}..., "
                f"client_id={client_id}, disconnected_at={elapsed:.1f}s ago"
            )
        
        return len(stale_sessions)
    
    async def broadcast_to_all(self, message: Dict) -> int:
        """
        Send a message to all connected clients.
        
        Args:
            message: Message dict to send
            
        Returns:
            Number of clients that received the message successfully
        """
        count = 0
        for client in self._clients.values():
            if await client.send_message(message):
                count += 1
        return count
    
    async def broadcast_to_capability(self, capability: str, message: Dict) -> int:
        """
        Send a message to all clients with a specific capability.
        
        Args:
            capability: Required capability
            message: Message dict to send
            
        Returns:
            Number of clients that received the message successfully
        """
        count = 0
        for client in self.get_by_capability(capability):
            if await client.send_message(message):
                count += 1
        return count
    
    async def broadcast_to_type(self, client_type: str, message: Dict) -> int:
        """
        Send a message to all clients of a specific type.
        
        Args:
            client_type: Required type (e.g., 'rpi', 'esp32')
            message: Message dict to send
            
        Returns:
            Number of clients that received the message successfully
        """
        count = 0
        for client in [c for c in self._clients.values() if c.client_type == client_type]:
            if await client.send_message(message):
                count += 1
        return count
    
    # ===== Player Instance Management (Phase 1+) =====
    
    def initialize_player_instances(self, device_config: Dict[str, str]):
        """
        Initialize player instances from device configuration.
        Creates one MediaPlayerService per configured device.
        
        Args:
            device_config: Dict mapping device_name -> backend_type
                          e.g., {"bedroom": "chromecast", "kitchen": "chromecast"}
        """
        from app.services import MediaPlayerService
        from app.playback_backends.factory import get_playback_backend_by_name
        from app.core.service_container import get_service
        
        if not hasattr(self, '_player_instances'):
            self._player_instances = {}
            self._client_active_instance = {}
        
        self._device_config = device_config
        
        for device_name, backend_type in device_config.items():
            if device_name not in self._player_instances:
                backend = get_playback_backend_by_name(backend_type, device_name)
                instance = MediaPlayerService(
                    event_bus=get_service("event_bus"),
                    playback_backend=backend,
                    device_name=device_name
                )
                self._player_instances[device_name] = instance
                logger.info(f"Created MediaPlayerService for device: {device_name}")
    
    def get_or_create_player_instance(self, device_name: str) -> Optional:
        """
        Get MediaPlayerService instance for device.
        Raises KeyError if device not in config.
        Device names are case-insensitive (normalized to lowercase).
        """
        if not hasattr(self, '_player_instances'):
            self._player_instances = {}
            self._client_active_instance = {}
            self._device_config = {}
        
        # Normalize device_name to lowercase for case-insensitive lookup
        device_name = device_name.lower()
        
        if device_name not in self._device_config:
            raise KeyError(
                f"Device '{device_name}' not configured. "
                f"Available: {list(self._device_config.keys())}"
            )
        
        if device_name not in self._player_instances:
            # Lazy create from config
            from app.services import MediaPlayerService
            from app.playback_backends.factory import get_playback_backend_by_name
            from app.core.service_container import get_service
            
            backend_type = self._device_config[device_name]
            backend = get_playback_backend_by_name(backend_type, device_name)
            instance = MediaPlayerService(
                event_bus=get_service("event_bus"),
                playback_backend=backend,
                device_name=device_name
            )
            self._player_instances[device_name] = instance
            logger.info(f"Lazy-created MediaPlayerService for device: {device_name}")
        
        return self._player_instances[device_name]
    
    def get_player_instance(self, device_name: str) -> Optional:
        """Get existing instance for device, or None.
        Device names are case-insensitive (normalized to lowercase).
        """
        if not hasattr(self, '_player_instances'):
            return None
        # Normalize device_name to lowercase for case-insensitive lookup
        device_name = device_name.lower()
        return self._player_instances.get(device_name)
    
    def set_client_active_instance(self, client_id: str, player_instance) -> None:
        """
        Client takes control of a specific MediaPlayerService instance.
        Multiple clients can control the same instance (shared control).
        """
        if not hasattr(self, '_client_active_instance'):
            self._client_active_instance = {}
        
        # Release old instance (if any)
        old_instance = self._client_active_instance.get(client_id)
        if old_instance and old_instance != player_instance:
            old_instance.active_clients.discard(client_id)
        
        # Take new instance
        self._client_active_instance[client_id] = player_instance
        player_instance.active_clients.add(client_id)
        
        logger.debug(
            f"Client {client_id} now controlling {player_instance.device_name}. "
            f"Active clients: {player_instance.active_clients}"
        )
    
    def release_client_instance(self, client_id: str) -> None:
        """Client releases control of its current instance."""
        if not hasattr(self, '_client_active_instance'):
            return
        
        instance = self._client_active_instance.pop(client_id, None)
        if instance:
            instance.active_clients.discard(client_id)
            logger.debug(
                f"Client {client_id} released {instance.device_name}. "
                f"Active clients: {instance.active_clients}"
            )
    
    def get_client_active_instance(self, client_id: str) -> Optional:
        """Which instance is this client currently controlling?"""
        if not hasattr(self, '_client_active_instance'):
            return None
        return self._client_active_instance.get(client_id)
    
    def get_instance_active_clients(self, device_name: str) -> set:
        """Which clients are currently controlling this instance?
        Device names are case-insensitive (normalized to lowercase).
        """
        if not hasattr(self, '_player_instances'):
            return set()
        # Normalize device_name to lowercase for case-insensitive lookup
        device_name = device_name.lower()
        instance = self._player_instances.get(device_name)
        if instance:
            return instance.active_clients.copy()
        return set()
    
    def list_player_instances(self) -> List:
        """Return all active MediaPlayerService instances."""
        if not hasattr(self, '_player_instances'):
            return []
        return list(self._player_instances.values())
    
    def list_client_instance_mappings(self) -> Dict:
        """
        Return all client -> instance mappings.
        Useful for API: shows which client controls which device.
        """
        if not hasattr(self, '_client_active_instance'):
            return {}
        return {
            client_id: instance.device_name 
            for client_id, instance in self._client_active_instance.items()
        }
    
    def list_instance_client_mappings(self) -> Dict:
        """
        Return all instance -> clients mappings.
        Useful for API: shows which clients control each instance.
        """
        if not hasattr(self, '_player_instances'):
            return {}
        result = {}
        for device_name, instance in self._player_instances.items():
            result[device_name] = list(instance.active_clients)
        return result
    
    def get_configured_devices(self) -> List[str]:
        """
        Return list of all configured physical devices.
        """
        if not hasattr(self, '_device_config'):
            return []
        return list(self._device_config.keys())

