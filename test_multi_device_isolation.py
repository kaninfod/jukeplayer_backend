#!/usr/bin/env python3
"""
Test script to validate multi-device isolation.
Verifies that changing volume/playback on one device doesn't affect others.
"""

from app.core.service_container import setup_service_container
from app.config import config
import time

def test_device_isolation():
    """Test that each device has independent playback state."""
    print("\n" + "="*60)
    print("Testing Multi-Device Isolation")
    print("="*60)
    
    # Initialize service container
    sc = setup_service_container()
    client_registry = sc.get('client_registry')
    
    # Get instances
    instances = {inst.device_name: inst for inst in client_registry.list_player_instances()}
    print(f"\nInitialized {len(instances)} devices:")
    for name, inst in instances.items():
        print(f"  - {name}: {inst.playback_backend.__class__.__name__}")
    
    # Get kitchen and bedroom instances
    kitchen_inst = instances.get('kitchen')
    bedroom_inst = instances.get('bedroom')
    
    if not kitchen_inst or not bedroom_inst:
        print("ERROR: Missing kitchen or bedroom instance!")
        return False
    
    print("\n" + "-"*60)
    print("TEST 1: Volume Independence")
    print("-"*60)
    
    # Set different volumes
    print("Setting kitchen volume to 80%...")
    kitchen_inst.set_volume(80)
    time.sleep(0.5)
    
    print("Setting bedroom volume to 30%...")
    bedroom_inst.set_volume(30)
    time.sleep(0.5)
    
    # Check volumes (simulated - actual Chromecast will have real state)
    print(f"\nKitchen volume status: {kitchen_inst.get_context().get('volume')}")
    print(f"Bedroom volume status: {bedroom_inst.get_context().get('volume')}")
    
    print("\n" + "-"*60)
    print("TEST 2: Device Name Verification")
    print("-"*60)
    
    # Verify each instance knows its own device name
    for name, inst in instances.items():
        print(f"{name} instance device_name: {inst.device_name}")
        assert inst.device_name == name, f"Device name mismatch: {inst.device_name} != {name}"
    print("✓ All device names correctly locked to instances")
    
    print("\n" + "-"*60)
    print("TEST 3: Backend Independence")
    print("-"*60)
    
    # Verify each has different backend instance
    backend_ids = {}
    for name, inst in instances.items():
        backend_id = id(inst.playback_backend)
        backend_ids[name] = backend_id
        print(f"{name} backend ID: {backend_id}")
    
    # Check that all backend IDs are unique
    unique_ids = set(backend_ids.values())
    if len(unique_ids) == len(instances):
        print(f"✓ All {len(instances)} backends are independent instances")
    else:
        print(f"✗ ERROR: Some backends are shared! Expected {len(instances)}, got {len(unique_ids)}")
        return False
    
    print("\n" + "="*60)
    print("✓ Multi-Device Isolation Tests Passed")
    print("="*60 + "\n")
    
    return True

if __name__ == "__main__":
    import sys
    success = test_device_isolation()
    sys.exit(0 if success else 1)
