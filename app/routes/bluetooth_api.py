"""Bluetooth JSON API (Phase C): adapter status, scan, pair/connect lifecycle,
and pulse sink lookup for speaker assignment. All blocking calls are wrapped
in asyncio.to_thread."""

import asyncio
import logging
import re

from fastapi import APIRouter, Body, HTTPException
from typing import Any, Dict, Optional

from app.core.service_container import get_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/bluetooth", tags=["bluetooth"])

_MAC_RE = re.compile(r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}")


def _bt():
    return get_service("bluetooth_service")


def _valid_mac(mac: str) -> bool:
    return bool(_MAC_RE.fullmatch(mac or ""))


def _require_mac(payload: Dict[str, Any]) -> str:
    mac = str((payload or {}).get("mac", "")).strip()
    if not _valid_mac(mac):
        raise HTTPException(status_code=400, detail="Invalid MAC address")
    return mac


@router.get("/status")
async def status():
    """Adapter state + every known device with pairing/connection flags."""
    bt = _bt()
    adapter = await asyncio.to_thread(bt.status)
    devices = await asyncio.to_thread(bt.devices)
    return {**adapter, "devices": devices}


@router.get("/scan")
async def scan(seconds: float = 0):
    """Open a radio scan window and return every discovered device with its
    pairing/connection flags (blocking — runs off the event loop)."""
    seconds = min(max(float(seconds), 5.0), 30.0) if seconds else None
    devices = await asyncio.to_thread(_bt().scan, seconds)
    return {"devices": devices}


@router.post("/pair")
async def pair(payload: Dict[str, Any] = Body(...)):
    """Pair + trust + connect in one step (the card's single-click flow)."""
    mac = _require_mac(payload)
    result = await asyncio.to_thread(_bt().pair_and_connect, mac)
    if not result["connected"]:
        raise HTTPException(status_code=502, detail=result.get("error") or "Pairing failed")
    return result


@router.post("/connect")
async def connect(payload: Dict[str, Any] = Body(...)):
    mac = _require_mac(payload)
    result = await asyncio.to_thread(_bt().connect, mac)
    if not result["connected"]:
        raise HTTPException(status_code=502, detail=result.get("error") or "Connect failed")
    return result


@router.post("/disconnect")
async def disconnect(payload: Dict[str, Any] = Body(...)):
    mac = _require_mac(payload)
    return await asyncio.to_thread(_bt().disconnect, mac)


@router.post("/forget")
async def forget(payload: Dict[str, Any] = Body(...)):
    mac = _require_mac(payload)
    return await asyncio.to_thread(_bt().forget, mac)


@router.get("/sinks")
async def sinks():
    """Currently registered bluez pulse sinks (connected BT devices)."""
    return {"sinks": await asyncio.to_thread(_bt().bluez_sinks)}