"""Backwards-compatibility shim: all Bluetooth/system interactions now live
in `app/services/bluetooth_service.py` (the single BT module). This module
re-exports the checker so existing imports keep working."""

from app.services.bluetooth_service import BluetoothAudioChecker  # noqa: F401

__all__ = ["BluetoothAudioChecker"]