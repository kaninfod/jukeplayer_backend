"""
Client Registry Service
Tracks connected hardware clients (RPi, ESP32, etc.) and their capabilities.
"""

import logging
import uuid
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ClientInfo:
    """Information about a connected client."""
    
    def __init__(self, client_id: str, client_type: str, user_name: str, 
                 capabilities: List[str], connected_at: datetime, client_ip: Optional[str] = None, websocket=None):
        """
        Args:
            client_id: System-generated UUID for this client
            client_type: Type of client ('rpi', 'esp32', etc.)
            user_name: User-defined name from client config
            capabilities: List of capabilities (e.g., ['nfc_reader', 'display'])
            connected_at: Timestamp when client connected
            client_ip: IP address of the client (used to identify same physical device)
            websocket: Reference to the WebSocket connection (if applicable)
        """
        self.client_id = client_id
        self.client_type = client_type
        self.user_name = user_name
        self.capabilities = capabilities
        self.connected_at = connected_at
        self.client_ip = client_ip
        self.websocket = websocket
    
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
        # Track by IP to detect same physical device reconnecting
        self._by_ip: Dict[str, str] = {}  # ip_address -> client_id
    
    def register(self, client_type: str, user_name: str, capabilities: List[str], 
                 client_ip: Optional[str] = None, websocket=None) -> ClientInfo:
        """
        Register a new connected client.
        
        If a client from the same IP is already registered, the old one is unregistered first.
        This handles the case where a device restarts and reconnects with a new name or ID.
        
        Args:
            client_type: Type of client ('rpi', 'esp32', etc.)
            user_name: User-defined name from client config
            capabilities: List of capabilities
            client_ip: IP address of the client (used to identify same physical device)
            websocket: Optional WebSocket connection reference
            
        Returns:
            ClientInfo object with generated client_id
        """
        # If this IP already has a registered client, unregister the old one
        if client_ip and client_ip in self._by_ip:
            old_client_id = self._by_ip[client_ip]
            logger.info(
                f"Client from IP {client_ip} reconnected with new name. "
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
            websocket=websocket
        )
        
        self._clients[client_id] = client_info
        
        # Track by name for collision handling
        if user_name not in self._by_name:
            self._by_name[user_name] = []
        self._by_name[user_name].append(client_id)
        
        # Track by IP
        if client_ip:
            self._by_ip[client_ip] = client_id
        
        logger.info(
            f"Client registered: {user_name} (ID: {client_id}, Type: {client_type}, "
            f"IP: {client_ip}, Capabilities: {capabilities})"
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
    
    def get_all(self) -> List[ClientInfo]:
        """Get all connected clients."""
        return list(self._clients.values())
    
    def get_by_capability(self, capability: str) -> List[ClientInfo]:
        """Get all clients with a specific capability."""
        return [c for c in self._clients.values() if capability in c.capabilities]
    
    def count(self) -> int:
        """Get total number of connected clients."""
        return len(self._clients)
