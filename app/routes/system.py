"""
System control routes for the jukebox.

Note: the /clients endpoints were removed — they depended on the removed
'client_registry' service and returned 500s. Client introspection lives in
/api/output/control_clients and /api/output/speakers instead.
"""
import logging

from fastapi import APIRouter
from typing import Dict, Any

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/ping")
async def ping() -> Dict[str, Any]:
    return {"status": "ok", "message": "Jukebox API is running"}