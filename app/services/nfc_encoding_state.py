"""
NFC Encoding State Service
Manages the lifecycle of NFC card encoding sessions
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


class NfcEncodingStateService:
    """
    Manages NFC encoding session state - single source of truth for encoding operations.
    
    This service tracks:
    - Whether an encoding session is active
    - The album being encoded
    - The client selected for encoding
    - The most recent card UID written
    - Success status of the encoding
    - Supports async waiting for client write_data responses
    """
    
    def __init__(self):
        self.active = False
        self.album_id = None
        self.client_id = None
        self.last_uid = None
        self.success = False
        self.error_message = None
        self.status = None
        self._completion_event = asyncio.Event()
        self._completion_result = None

    def start(self, album_id: str, client_id: str = None) -> None:
        """Start an NFC encoding session for the given album and optional client."""
        self.active = True
        self.album_id = album_id
        self.client_id = client_id
        self.last_uid = None
        self.success = False
        self.error_message = None
        self.status = None
        # Reset completion event for new session
        try:
            self._completion_event = asyncio.Event()
        except RuntimeError:
            # If there's no running event loop, create a simple Event later
            self._completion_event = None
        self._completion_result = None
        logger.info(f"NFC encoding session started for album_id={album_id}, client_id={client_id}")

    def stop(self) -> None:
        """Stop the current NFC encoding session."""
        self.active = False
        self.album_id = None
        self.client_id = None
        self.last_uid = None
        self.success = False
        self.error_message = None
        self.status = None
        logger.info("NFC encoding session stopped")
        
    def set_result(self, status: str, uid: str = None, error_message: str = None) -> None:
        """Set the result from a client's write_data response.
        
        Args:
            status: "success", "timeout", or "error"
            uid: Card UID if successful
            error_message: Error message if status is "error" or "timeout"
        """
        self.status = status
        self.last_uid = uid
        self.error_message = error_message
        self.success = (status == "success")
        self.active = False
        
        logger.info(f"NFC encoding result received - status={status}, uid={uid}")
        
        # Signal any waiting tasks
        if self._completion_event:
            self._completion_event.set()
        
        self._completion_result = {
            "status": status,
            "uid": uid,
            "error_message": error_message
        }

    async def wait_for_completion(self, timeout: float = 30) -> dict:
        """Wait for NFC encoding to complete (client sends response).
        
        Args:
            timeout: Maximum seconds to wait (default 30)
            
        Returns:
            Dict with status, uid, error_message
            
        Raises:
            asyncio.TimeoutError: If timeout is exceeded
        """
        if not self._completion_event:
            try:
                self._completion_event = asyncio.Event()
            except RuntimeError:
                raise
        
        try:
            await asyncio.wait_for(self._completion_event.wait(), timeout=timeout)
            return self._completion_result or {"status": "timeout", "uid": None, "error_message": "No result received"}
        except asyncio.TimeoutError:
            logger.warning(f"NFC encoding request timed out after {timeout}s")
            self.active = False
            raise

    def complete(self, uid) -> None:
        """Mark the current encoding session as complete with the given card UID."""
        self.last_uid = uid
        self.success = True
        self.active = False
        logger.info(f"NFC encoding session completed: UID={uid}")

    def is_active(self) -> bool:
        """Check if an encoding session is currently active."""
        return self.active
    
    def get_album_id(self) -> str:
        """Get the album being encoded."""
        return self.album_id
    
    def get_client_id(self) -> str:
        """Get the client selected for encoding."""
        return self.client_id
    
    def get_last_uid(self) -> any:
        """Get the most recently encoded card UID."""
        return self.last_uid
    
    def was_successful(self) -> bool:
        """Check if the last encoding was successful."""
        return self.success
