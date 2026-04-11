"""
Client Registry Service
Tracks connected hardware clients (RPi, ESP32, etc.) and their capabilities.
Manages persistent client connections and event broadcasting.
"""

import asyncio
import logging
import uuid
from typing import Dict, List, Optional, Callable
from datetime import datetime

logger = logging.getLogger(__name__)


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
    
    def register(self, client_type: str, user_name: str, capabilities: List[str], 
                 client_ip: Optional[str] = None, websocket=None, send_callback: Optional[Callable] = None,
                 session_token: Optional[str] = None) -> ClientInfo:
        """
        Register a new connected client.
        
        For hardware clients: If a client from the same IP is already registered, the old one is 
        unregistered first. This handles the case where a device restarts and reconnects with a new name or ID.
        
        For web clients: Uses session_token to uniquely identify each session. If a web client reconnects
        with the same session token, the old connection is unregistered first.
        
        Args:
            client_type: Type of client ('rpi', 'esp32', 'web', etc.)
            user_name: User-defined name from client config
            capabilities: List of capabilities
            client_ip: IP address of the client (used to identify same physical device for hardware)
            websocket: Optional WebSocket connection reference
            send_callback: Optional async function(message) to send messages to this client
            session_token: Unique session token for web clients (generated and stored in browser)
            
        Returns:
            ClientInfo object with generated client_id
        """
        # For web clients with session token: unregister old connection if it exists
        if client_type == "web" and session_token:
            if session_token in self._by_session_token:
                old_client_id = self._by_session_token[session_token]
                logger.info(
                    f"Web client reconnected with same session token. "
                    f"Unregistering previous entry (ID: {old_client_id})"
                )
                self.unregister(old_client_id)
        
        # For hardware clients only: unregister old connection from same IP
        elif client_type != "web" and client_ip and client_ip in self._by_ip:
            old_client_id = self._by_ip[client_ip]
            logger.info(
                f"Hardware client from IP {client_ip} reconnected. "
                f"Unregistering previous entry (ID: {old_client_id})"
            )
            self.unregister(old_client_id)
        
        client_id = str(uuid.uuid4())
        now = datetime.now()
        
        client_info = ClientInfo(
            client_id=client_id,
            client_type=client_type,
            user_name=user_name,
            capabilities=capabilities,
            connected_at=now,
            client_ip=client_ip,
            websocket=websocket,
            send_callback=send_callback,
            session_token=session_token
        )
        
        self._clients[client_id] = client_info
        
        # Track by name for collision handling
        if user_name not in self._by_name:
            self._by_name[user_name] = []
        self._by_name[user_name].append(client_id)
        
        # Track by IP (only for hardware clients)
        if client_ip and client_type != "web":
            self._by_ip[client_ip] = client_id
        
        # Track by session token (only for web clients)
        if session_token:
            self._by_session_token[session_token] = client_id
        
        logger.info(
            f"Client registered: {user_name} (ID: {client_id}, Type: {client_type}, "
            f"IP: {client_ip}, Session: {session_token}, Capabilities: {capabilities})"
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
        
        # Remove from session token index
        if client_info.session_token and client_info.session_token in self._by_session_token:
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

