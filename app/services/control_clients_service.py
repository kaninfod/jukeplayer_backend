import logging
from typing import Dict, Optional, Callable, List
from datetime import datetime
import uuid
from app.core import event_bus, EventType, Event

logger = logging.getLogger(__name__)

class ControlClient:
    def __init__(self, client_id: str, client_type: str, user_name: str, 
                capabilities: List[str], connected_at: datetime, client_ip: Optional[str] = None, 
                websocket=None, send_callback: Optional[Callable] = None, session_token: Optional[str] = None,
                speaker_name: Optional[str] = None):
        
        self.client_id = client_id
        self.client_type = client_type
        self.user_name = user_name
        self.capabilities = capabilities
        self.connected_at = connected_at
        self.client_ip = client_ip
        self.websocket = websocket
        self.send_callback = send_callback
        self.session_token = session_token
        self.speaker_name = speaker_name
        self.ws_active = True 


    def to_dict(self):
        #from app.core.service_container import get_service
        #speakers_service = get_service("speakers_service")
        #speaker = speakers_service.get_speaker(speaker_name=self.speaker_name)
        #if speaker:
            #speaker_info = speaker.to_dict()
        #else:
            #speaker_info = None
        return {
            "client_id": self.client_id,
            "client_type": self.client_type,
            "user_name": self.user_name,
            "capabilities": self.capabilities,
            "connected_at": self.connected_at.isoformat(),
            "client_ip": self.client_ip,
            "speaker_name": self.speaker_name,
            #"speaker_info": speaker_info,
            "ws_active": self.ws_active
        }


class ControlClientsService:
    def __init__(self):
        self._clients: Dict[str, ControlClient] = {}


    async def register(self, payload: Dict[str, any]) -> ControlClient:

        client_id = payload.get("client_id") if payload.get("client_id") is not None else str(uuid.uuid4())
        client_type = payload.get("client_type")
        user_name = payload.get("user_name")
        capabilities = payload.get("capabilities")
        client_ip = payload.get("client_ip")
        websocket = payload.get("websocket")
        send_callback = payload.get("send_callback")
        speaker_name = payload.get("device_name")
        
        try:
            control_client = self._clients.get(client_id) if client_id else None
            
            if control_client:
                logger.info(f"[ControlClientsService]  Client with ID {client_id} already exists. Updating existing client info.")
                control_client.client_type = client_type
                control_client.user_name = user_name
                control_client.capabilities = capabilities
                control_client.client_ip = client_ip
                control_client.websocket = websocket
                control_client.send_callback = send_callback
                control_client.speaker_name = speaker_name
                control_client.ws_active = True
            
            else:

                control_client = ControlClient(
                    client_id=client_id,
                    client_type=client_type,
                    user_name=user_name,
                    capabilities=capabilities,
                    connected_at=datetime.now(),
                    client_ip=client_ip,
                    websocket=websocket,
                    send_callback=send_callback,
                    session_token=None,
                    speaker_name=speaker_name
                )
            
                self._clients[control_client.client_id] = control_client

            logger.info(f"[ControlClientsService]  Registered control client: {control_client.client_id} (Type: {control_client.client_type}, User: {control_client.user_name}, Speaker: {control_client.speaker_name})")
            logger.debug(f"[ControlClientsService]  Current control clients: {list(self._clients.keys())}")

            if speaker_name:
                logger.info(f"[ControlClientsService]  Client {control_client.client_id} associated with speaker {speaker_name}")
                result = await event_bus.aemit(Event(
                    type=EventType.ASSIGN_SPEAKER,
                    payload={"client_id": client_id, "speaker_name": speaker_name}
                ))

            return control_client    
        
        except Exception as e:
            logger.warning(f"Error: {client_id}: {e}")
        
        
    
    def unregister(self, client_id: str):
        try:
            if client_id in self._clients:
                del self._clients[client_id]
                logger.info(f"[ControlClientsService]  Unregistered control client: {client_id}")
            else:
                logger.warning(f"[ControlClientsService]  Attempted to unregister non-existent client ID: {client_id}")
        except Exception as e:
            logger.error(f"[ControlClientsService]  Error unregistering client {client_id}: {e}")

    def set_client_active(self, client_id: str, active: bool):
        try:
            client = self._clients.get(client_id)
            if client:
                client.ws_active = active
                logger.info(f"[ControlClientsService]  Set client {client_id} active status to {active}")
            else:
                logger.warning(f"[ControlClientsService]  Attempted to set active status for non-existent client ID: {client_id}")
        except Exception as e:
            logger.error(f"[ControlClientsService]  Error setting client {client_id} active status: {e}")

    def get_client(self, client_id: str) -> Optional[ControlClient]:
        return self._clients.get(client_id)
    
    def get_all_clients(self, capability: str = "") -> Dict[str, ControlClient]:
        if capability:
            return {client_id: client for client_id, client in self._clients.items() if capability in client.capabilities}
        return self._clients
    
    def to_dict(self):
        result = {} 
        for control_client in self._clients.values():
            result[control_client.client_id] = control_client.to_dict()
        
        return result
