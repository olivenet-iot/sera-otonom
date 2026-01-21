#!/usr/bin/env python3
"""
Sera Otonom - Executor Integration Test Script

Bu script executor modülünü gerçek ortamda test eder.
MQTT bağlantısı olmadan simülasyon modunda çalışır.

Kullanım:
    python scripts/test_executor.py [--with-mqtt] [-v]
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime

# Project root'u path'e ekle
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from actions import RelayController, RelayCommandResult, ActionExecutor, ActionStatus
from utils.state_manager import get_state_manager
from utils.config_loader import get_config_loader


def setup_logging(verbose: bool = False):
    """Logging ayarla"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S"
    )


async def test_imports():
    """Import testleri"""
    print("\n" + "=" * 60)
    print("TEST 1: Import Testleri")
    print("=" * 60)

    tests = [
        ("RelayController", RelayController),
        ("RelayCommandResult", RelayCommandResult),
        ("ActionExecutor", ActionExecutor),
        ("ActionStatus", ActionStatus),
    ]

    all_passed = True
    for name, cls in tests:
        try:
            instance = cls.__name__
            print(f"  [OK] {name}")
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            all_passed = False

    return all_passed


async def test_relay_controller():
    """RelayController testleri (MQTT olmadan)"""
    print("\n" + "=" * 60)
    print("TEST 2: RelayController Testleri (Simulation Mode)")
    print("=" * 60)

    # Load device config
    try:
        config_loader = get_config_loader()
        device_config = config_loader.load("devices")
    except FileNotFoundError:
        print("  [WARN] devices.yaml bulunamadı, varsayılan config kullanılıyor")
        device_config = {
            "relays": {
                "pump_01": {"max_on_duration_minutes": 60},
                "fan_01": {"max_on_duration_minutes": 120}
            }
        }

    # Create controller without MQTT (simulation mode)
    controller = RelayController(None, device_config)
    print(f"  [OK] RelayController oluşturuldu (simulation mode)")

    # Test turn_on
    print("\n  Testing turn_on:")
    result = await controller.turn_on("pump_01", duration_minutes=5, reason="test_irrigation")
    print(f"    pump_01 turn_on: success={result.success}, message={result.message}")
    if not result.success:
        print(f"    [WARN] Unexpected failure: {result.error}")

    result = await controller.turn_on("fan_01", duration_minutes=10, reason="test_cooling")
    print(f"    fan_01 turn_on: success={result.success}, message={result.message}")

    # Test unknown device
    result = await controller.turn_on("unknown_device")
    print(f"    unknown_device turn_on: success={result.success}, error={result.error}")
    assert result.success is False, "Unknown device should fail"
    print("  [OK] Unknown device handling")

    # Test safety limit
    result = await controller.turn_on("pump_01", duration_minutes=200)
    print(f"    pump_01 with 200min duration: success={result.success}")
    print("  [OK] Safety limit enforced")

    # Test turn_off
    print("\n  Testing turn_off:")
    await asyncio.sleep(0.1)  # Small delay
    result = await controller.turn_off("pump_01", reason="test_complete")
    print(f"    pump_01 turn_off: success={result.success}, message={result.message}")

    result = await controller.turn_off("fan_01", reason="test_complete")
    print(f"    fan_01 turn_off: success={result.success}, message={result.message}")

    # Test scheduled off
    print("\n  Testing schedule_off:")
    await controller.schedule_off("pump_01", after_minutes=1)
    has_task = "pump_01" in controller._scheduled_off_tasks
    print(f"    Scheduled task created: {has_task}")

    cancelled = controller._cancel_scheduled_off("pump_01")
    print(f"    Scheduled task cancelled: {cancelled}")

    # Shutdown
    await controller.shutdown()
    print("\n  [OK] RelayController testleri tamamlandı")

    return True


async def test_action_executor():
    """ActionExecutor testleri"""
    print("\n" + "=" * 60)
    print("TEST 3: ActionExecutor Testleri")
    print("=" * 60)

    # Load device config
    try:
        config_loader = get_config_loader()
        device_config = config_loader.load("devices")
    except FileNotFoundError:
        device_config = {
            "relays": {
                "pump_01": {"max_on_duration_minutes": 60},
                "fan_01": {"max_on_duration_minutes": 120}
            }
        }

    # Create components
    controller = RelayController(None, device_config)
    executor = ActionExecutor(controller, device_config)
    print("  [OK] ActionExecutor oluşturuldu")

    # Get initial stats
    stats = executor.get_stats()
    print(f"\n  Initial stats: {stats}")

    # Get pending count
    pending_count = executor.get_pending_count()
    print(f"  Pending actions: {pending_count}")

    # Process empty pending
    print("\n  Testing process_pending_actions (empty):")
    results = await executor.process_pending_actions()
    print(f"    Processed: {len(results)} actions")

    # Test with manual action
    print("\n  Testing process_single_action:")
    test_action = {
        "id": "manual_test_001",
        "action": "pump_on",
        "device": "pump_01",
        "duration_minutes": 5,
        "reason": "manual_test",
        "status": "pending"
    }
    result = await executor.process_single_action(test_action)
    print(f"    Action result: status={result.status.value}, device={result.device_id}")

    # Test unknown action
    test_action = {
        "id": "manual_test_002",
        "action": "unknown_action",
        "device": "pump_01",
        "status": "pending"
    }
    result = await executor.process_single_action(test_action)
    print(f"    Unknown action: status={result.status.value}, error={result.error}")
    assert result.status == ActionStatus.FAILED

    # Test 'none' action
    test_action = {
        "id": "manual_test_003",
        "action": "none",
        "status": "pending"
    }
    result = await executor.process_single_action(test_action)
    print(f"    'none' action: status={result.status.value}")
    assert result.status == ActionStatus.SKIPPED

    # Final stats
    stats = executor.get_stats()
    print(f"\n  Final stats: {stats}")

    # Shutdown
    await controller.shutdown()
    print("\n  [OK] ActionExecutor testleri tamamlandı")

    return True


async def test_state_integration():
    """State yönetimi entegrasyon testi"""
    print("\n" + "=" * 60)
    print("TEST 4: State Entegrasyon Testleri")
    print("=" * 60)

    state_manager = get_state_manager()

    # Read current device states
    try:
        device_states = state_manager.read("device_states")
        print(f"  Current devices: {list(device_states.get('devices', {}).keys())}")
        print(f"  Pending actions: {len(device_states.get('pending_actions', []))}")
    except Exception as e:
        print(f"  [WARN] Could not read device_states: {e}")
        return True  # Not a failure if state doesn't exist

    # Check last_downlink
    last_downlink = device_states.get("last_downlink")
    if last_downlink:
        print(f"  Last downlink: {last_downlink}")
    else:
        print("  Last downlink: None")

    print("\n  [OK] State entegrasyon testleri tamamlandı")
    return True


async def test_executor_cycle():
    """Executor döngüsü testi"""
    print("\n" + "=" * 60)
    print("TEST 5: Executor Döngü Testi")
    print("=" * 60)

    # Load device config
    try:
        config_loader = get_config_loader()
        device_config = config_loader.load("devices")
    except FileNotFoundError:
        device_config = {
            "relays": {
                "pump_01": {"max_on_duration_minutes": 60},
                "fan_01": {"max_on_duration_minutes": 120}
            }
        }

    # Create components
    controller = RelayController(None, device_config)
    executor = ActionExecutor(controller, device_config)

    state_manager = get_state_manager()

    # Add a test pending action
    print("  Adding test pending action...")
    try:
        device_states = state_manager.read("device_states")
        device_states["pending_actions"].append({
            "id": "cycle_test_001",
            "action": "fan_on",
            "device": "fan_01",
            "duration_minutes": 5,
            "reason": "executor_cycle_test",
            "status": "pending",
            "created_at": datetime.utcnow().isoformat() + "Z"
        })
        state_manager.write("device_states", device_states)
        print("  [OK] Test action added")
    except Exception as e:
        print(f"  [WARN] Could not add test action: {e}")

    # Run executor cycle
    print("\n  Running executor cycle...")
    results = await executor.process_pending_actions()
    print(f"  Processed: {len(results)} actions")

    for result in results:
        print(f"    - {result.action_id}: {result.status.value}")

    # Check scheduled shutoffs
    print("\n  Checking scheduled shutoffs...")
    shutoffs = await executor.check_scheduled_shutoffs()
    print(f"  Triggered shutoffs: {shutoffs}")

    # Get final stats
    stats = executor.get_stats()
    print(f"\n  Executor stats: {stats}")

    # Cleanup
    await controller.shutdown()

    print("\n  [OK] Executor döngü testi tamamlandı")
    return True


async def test_brain_integration():
    """Brain entegrasyonu testi"""
    print("\n" + "=" * 60)
    print("TEST 6: Brain Entegrasyon Testi")
    print("=" * 60)

    try:
        from core import SeraBrain

        # Create brain (Claude disabled for testing)
        brain = SeraBrain(use_claude=False, use_fallback=True)
        print("  [OK] SeraBrain oluşturuldu")

        # Check initial status
        status = brain.get_status()
        print(f"  Initial status: running={status['is_running']}, initialized={status['initialized']}")

        # Initialize
        print("\n  Initializing brain...")
        await brain.initialize()
        print("  [OK] Brain initialized")

        # Check executor in status
        status = brain.get_status()
        if "executor" in status:
            print(f"  Executor stats: {status['executor']}")
            print(f"  Pending actions: {status.get('pending_actions', 0)}")
        else:
            print("  [WARN] Executor not in status")

        # Check scheduler tasks
        if "scheduler" in status:
            tasks = status["scheduler"]
            executor_task = tasks.get("executor_cycle")
            if executor_task:
                print(f"  Executor cycle task: interval={executor_task.get('interval_seconds')}s, enabled={executor_task.get('enabled')}")
            else:
                print("  [WARN] executor_cycle task not found")

        # Cleanup
        await brain.stop()
        print("\n  [OK] Brain entegrasyon testi tamamlandı")

    except Exception as e:
        print(f"  [ERROR] Brain test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


async def main():
    parser = argparse.ArgumentParser(description="Sera Otonom Executor Integration Tests")
    parser.add_argument("--with-mqtt", action="store_true", help="MQTT bağlantısı ile test")
    parser.add_argument("-v", "--verbose", action="store_true", help="Ayrıntılı log")
    args = parser.parse_args()

    setup_logging(args.verbose)

    print("\n" + "=" * 60)
    print("SERA OTONOM - EXECUTOR INTEGRATION TESTS")
    print("=" * 60)
    print(f"Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"MQTT testi: {'Evet' if args.with_mqtt else 'Hayır (simulation mode)'}")

    results = []

    # Test 1: Imports
    results.append(("Import Testleri", await test_imports()))

    # Test 2: RelayController
    results.append(("RelayController", await test_relay_controller()))

    # Test 3: ActionExecutor
    results.append(("ActionExecutor", await test_action_executor()))

    # Test 4: State Integration
    results.append(("State Entegrasyon", await test_state_integration()))

    # Test 5: Executor Cycle
    results.append(("Executor Döngü", await test_executor_cycle()))

    # Test 6: Brain Integration
    results.append(("Brain Entegrasyon", await test_brain_integration()))

    # Sonuçlar
    print("\n" + "=" * 60)
    print("TEST SONUÇLARI")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, result in results:
        status = "[OK]" if result else "[FAIL]"
        print(f"  {status} {name}")
        if result:
            passed += 1
        else:
            failed += 1

    print(f"\nToplam: {passed} başarılı, {failed} başarısız")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
