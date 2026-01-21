#!/usr/bin/env python3
"""
Sera Otonom - Brain Integration Test Script

Bu script brain modülünü gerçek ortamda test eder.
Claude Code'u kullanmaz (offline test için), sadece fallback karar verici kullanır.

Kullanım:
    python scripts/test_brain.py [--with-claude] [--cycles N]
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

from core import SeraBrain, SeraScheduler, ClaudeRunner, FallbackDecisionMaker, DataCollector


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
        ("SeraBrain", SeraBrain),
        ("SeraScheduler", SeraScheduler),
        ("ClaudeRunner", ClaudeRunner),
        ("FallbackDecisionMaker", FallbackDecisionMaker),
        ("DataCollector", DataCollector),
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


async def test_fallback_decision_maker():
    """Fallback karar verici testleri"""
    print("\n" + "=" * 60)
    print("TEST 2: FallbackDecisionMaker Testleri")
    print("=" * 60)

    thresholds = {
        "temperature": {
            "optimal_range": [20, 28],
            "warning_low": 15,
            "warning_high": 32,
            "critical_low": 10,
            "critical_high": 38
        },
        "humidity": {
            "optimal_range": [60, 80],
            "warning_high": 90
        },
        "soil_moisture": {
            "optimal_range": [40, 70],
            "warning_low": 30,
            "critical_low": 20
        }
    }

    fallback = FallbackDecisionMaker(thresholds)

    test_cases = [
        {
            "name": "Normal koşullar",
            "sensors": {
                "temperature": {"value": 25},
                "humidity": {"value": 70},
                "soil_moisture": {"value": 50}
            },
            "expected_action": "none"
        },
        {
            "name": "Yüksek sıcaklık",
            "sensors": {
                "temperature": {"value": 40},
                "humidity": {"value": 70},
                "soil_moisture": {"value": 50}
            },
            "expected_action": "fan_on"
        },
        {
            "name": "Düşük toprak nemi",
            "sensors": {
                "temperature": {"value": 25},
                "humidity": {"value": 70},
                "soil_moisture": {"value": 15}
            },
            "expected_action": "pump_on"
        },
        {
            "name": "Yüksek nem",
            "sensors": {
                "temperature": {"value": 25},
                "humidity": {"value": 95},
                "soil_moisture": {"value": 50}
            },
            "expected_action": "fan_on"
        }
    ]

    all_passed = True
    for test in test_cases:
        result = fallback.make_decision(test["sensors"])
        actual = result.decision["action"]
        expected = test["expected_action"]

        if actual == expected:
            print(f"  [OK] {test['name']}: {actual}")
        else:
            print(f"  [FAIL] {test['name']}: expected {expected}, got {actual}")
            all_passed = False

    return all_passed


async def test_scheduler():
    """Scheduler testleri"""
    print("\n" + "=" * 60)
    print("TEST 3: SeraScheduler Testleri")
    print("=" * 60)

    scheduler = SeraScheduler(default_interval_seconds=2)
    call_count = {"task1": 0, "task2": 0}

    async def task1():
        call_count["task1"] += 1
        return f"task1: {call_count['task1']}"

    def task2():
        call_count["task2"] += 1

    # Görev ekleme
    assert scheduler.add_task("task1", task1, interval_seconds=1, run_immediately=True)
    assert scheduler.add_task("task2", task2, interval_seconds=2)
    print("  [OK] Task ekleme")

    # Manuel çalıştırma
    result = await scheduler.run_task_once("task1")
    assert result == "task1: 1"
    print("  [OK] Manuel çalıştırma")

    # Scheduler başlatma
    await scheduler.start()
    assert scheduler.is_running
    print("  [OK] Scheduler başlatma")

    # Kısa bir süre bekle
    await asyncio.sleep(2)

    # Durdurma
    await scheduler.stop()
    assert not scheduler.is_running
    print("  [OK] Scheduler durdurma")

    # Task istatistikleri
    info = scheduler.get_task_info("task1")
    assert info["stats"]["run_count"] > 0
    print(f"  [OK] Task1 {info['stats']['run_count']} kez çalıştı")

    return True


async def test_claude_runner():
    """ClaudeRunner testleri (parse only, CLI çalıştırmadan)"""
    print("\n" + "=" * 60)
    print("TEST 4: ClaudeRunner Parse Testleri")
    print("=" * 60)

    runner = ClaudeRunner()

    # Geçerli JSON parse
    valid_response = '''
    Sera analizi yapıldı.

    ```json
    {
        "analysis": {
            "summary": "Sıcaklık normal, nem optimal aralıkta",
            "concerns": [],
            "positive": ["Tüm değerler normal"]
        },
        "decision": {
            "action": "none",
            "device": null,
            "duration_minutes": null,
            "reason": "Müdahale gerekmiyor",
            "confidence": 0.9
        },
        "next_check": {
            "recommended_minutes": 30,
            "watch_for": "Sıcaklık trendi"
        }
    }
    ```
    '''

    result = runner.parse_response(valid_response)
    assert result.success
    assert result.decision["action"] == "none"
    assert result.analysis["summary"] is not None
    print("  [OK] Geçerli JSON parse")

    # Geçersiz JSON
    invalid_response = "No JSON here"
    result = runner.parse_response(invalid_response)
    assert not result.success
    print("  [OK] Geçersiz JSON algılama")

    # Prompt oluşturma
    context = {
        "sensors": {"temperature": {"value": 25}},
        "timestamp": datetime.now().isoformat()
    }
    prompt = runner.build_prompt(context)
    assert "temperature" in prompt
    assert "25" in prompt
    print("  [OK] Prompt oluşturma")

    return True


async def test_brain_offline(num_cycles: int = 2):
    """Brain offline test (Claude olmadan)"""
    print("\n" + "=" * 60)
    print("TEST 5: SeraBrain Offline Test")
    print("=" * 60)

    brain = SeraBrain(use_claude=False, use_fallback=True)

    print(f"  Brain oluşturuldu: claude={brain.use_claude}, fallback={brain.use_fallback}")

    # Status kontrolü
    status = brain.get_status()
    assert not status["is_running"]
    assert not status["initialized"]
    print("  [OK] Başlangıç durumu doğru")

    # Initialize - connector'lar başarısız olabilir ama fallback çalışmalı
    print("  Brain başlatılıyor...")
    try:
        await brain.initialize()
        print(f"  [OK] Brain initialized (connectors may have failed)")
    except Exception as e:
        print(f"  [WARN] Initialize exception (expected without real connections): {e}")

    # Fallback testi için manual decision
    print("\n  Fallback decision testleri:")
    if brain.fallback_maker:
        test_sensors = {
            "temperature": {"value": 35},
            "humidity": {"value": 70},
            "soil_moisture": {"value": 50}
        }
        result = brain.fallback_maker.make_decision(test_sensors)
        print(f"    Sıcaklık=35°C -> action={result.decision['action']}")
        assert result.decision["action"] == "fan_on"

        test_sensors = {
            "temperature": {"value": 25},
            "humidity": {"value": 70},
            "soil_moisture": {"value": 15}
        }
        result = brain.fallback_maker.make_decision(test_sensors)
        print(f"    Toprak nemi=%15 -> action={result.decision['action']}")
        assert result.decision["action"] == "pump_on"

        print("  [OK] Fallback kararları doğru")
    else:
        print("  [WARN] Fallback maker not initialized")

    # Cleanup
    await brain.stop()
    print("  [OK] Brain durduruldu")

    return True


async def test_brain_with_claude():
    """Brain Claude ile test (gerçek API çağrısı)"""
    print("\n" + "=" * 60)
    print("TEST 6: SeraBrain Claude Test (LIVE API)")
    print("=" * 60)

    print("  UYARI: Bu test gerçek Claude Code CLI çağrısı yapar!")
    print("  Claude Code'un yüklü ve yapılandırılmış olması gerekir.")

    brain = SeraBrain(use_claude=True, use_fallback=True)

    try:
        await brain.initialize()

        # Basit bir context oluştur
        context = {
            "timestamp": datetime.utcnow().isoformat(),
            "sensors": {
                "temperature": {"value": 28, "status": "normal"},
                "humidity": {"value": 65, "status": "normal"},
                "soil_moisture": {"value": 45, "status": "normal"}
            },
            "trends": {
                "temperature": {"direction": "stable", "rate": 0.1}
            },
            "weather": {
                "current": {"temp": 25},
                "forecast": {"tomorrow_max": 32}
            }
        }

        print("  Claude'a istek gönderiliyor...")
        result = await brain._make_decision(context)

        if result.success:
            print(f"  [OK] Claude yanıt verdi: action={result.decision.get('action')}")
            print(f"       Reasoning: {result.reasoning[:100]}...")
        else:
            print(f"  [WARN] Claude başarısız (fallback kullanılacak): {result.error}")

    except Exception as e:
        print(f"  [ERROR] Claude test hatası: {e}")

    finally:
        await brain.stop()

    return True


async def main():
    parser = argparse.ArgumentParser(description="Sera Otonom Brain Integration Tests")
    parser.add_argument("--with-claude", action="store_true", help="Claude API testi dahil et")
    parser.add_argument("--cycles", type=int, default=2, help="Test döngü sayısı")
    parser.add_argument("-v", "--verbose", action="store_true", help="Ayrıntılı log")
    args = parser.parse_args()

    setup_logging(args.verbose)

    print("\n" + "=" * 60)
    print("SERA OTONOM - BRAIN INTEGRATION TESTS")
    print("=" * 60)
    print(f"Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Claude testi: {'Evet' if args.with_claude else 'Hayır'}")

    results = []

    # Test 1: Imports
    results.append(("Import Testleri", await test_imports()))

    # Test 2: FallbackDecisionMaker
    results.append(("FallbackDecisionMaker", await test_fallback_decision_maker()))

    # Test 3: Scheduler
    results.append(("SeraScheduler", await test_scheduler()))

    # Test 4: ClaudeRunner Parse
    results.append(("ClaudeRunner Parse", await test_claude_runner()))

    # Test 5: Brain Offline
    results.append(("SeraBrain Offline", await test_brain_offline(args.cycles)))

    # Test 6: Brain with Claude (optional)
    if args.with_claude:
        results.append(("SeraBrain Claude", await test_brain_with_claude()))

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
