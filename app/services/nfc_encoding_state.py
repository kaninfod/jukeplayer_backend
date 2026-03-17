"""
NFC Encoding State Service
Manages the lifecycle of NFC card encoding sessions
"""

import logging

logger = logging.getLogger(__name__)


class NfcEncodingStateService:
    """
    Manages NFC encoding session state - single source of truth for encoding operations.
    
    This service tracks:
    - Whether an encoding session is active
    - The album being encoded
    - The most recent card UID written
    - Success status of the encoding
    """
    
    def __init__(self):
        self.active = False
        self.album_id = None
        self.last_uid = None
        self.success = False

    def start(self, album_id: str) -> None:
        """Start an NFC encoding session for the given album."""
        self.active = True
        self.album_id = album_id
        self.last_uid = None
        self.success = False
        logger.info(f"NFC encoding session started for album_id={album_id}")

    def stop(self) -> None:
        """Stop the current NFC encoding session."""
        self.active = False
        self.album_id = None
        self.last_uid = None
        self.success = False
        logger.info("NFC encoding session stopped")

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
    
    def get_last_uid(self) -> any:
        """Get the most recently encoded card UID."""
        return self.last_uid
    
    def was_successful(self) -> bool:
        """Check if the last encoding was successful."""
        return self.success
