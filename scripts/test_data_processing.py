#!/usr/bin/env python3
"""
Sera Otonom - Data Processing Integration Test

Bu script Phase 3'te implement edilen veri işleme modüllerini test eder:
- WeatherConnector (OpenWeatherMap API)
- SensorProcessor (sensör verisi işleme)
- TrendAnalyzer (trend analizi)

Kullanım:
    python scripts/test_data_processing.py

Not: Weather API testi için .env dosyasında WEATHER_API_KEY tanımlı olmalı.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Project root'u path'e ekle
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from utils.config_loader import get_config, get_config_loader
from connectors.weather import WeatherConnector
from processors.sensor_processor import SensorProcessor
from processors.trend_analyzer import TrendAnalyzer


def print_section(title: str) -> None:
    """Print section header"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_result(test_name: str, success: bool, details: str = "") -> None:
    """Print test result"""
    status = "✓ PASS" if success else "✗ FAIL"
    print(f"  {status}: {test_name}")
    if details:
        print(f"         {details}")


async def test_weather_connector() -> bool:
    """Test WeatherConnector"""
    print_section("WeatherConnector Test")

    try:
        # Config yükle
        settings = get_config("settings")
        weather_config = settings.get("weather", {})

        api_key = weather_config.get("api_key", "")

        # API key kontrolü
        if not api_key or api_key.startswith("${"):
            print("  ! WEATHER_API_KEY tanımlı değil, API testleri atlanıyor")
            print("  ! .env dosyasında WEATHER_API_KEY değişkenini tanımlayın")

            # Sadece initialization test
            connector = WeatherConnector(weather_config)
            print_result("Connector initialization", True)
            return True

        connector = WeatherConnector(weather_config)
        print_result("Connector initialization", True)

        # Connect test
        connected = await connector.connect()
        print_result("Session creation", connected)

        if not connected:
            return False

        # Health check
        health = await connector.health_check()
        print_result("Health check", health.get("healthy", False),
                    f"Status: {health.get('status_code', 'N/A')}")

        if not health.get("healthy"):
            print(f"         Error: {health.get('error', 'Unknown')}")
            await connector.disconnect()
            return False

        # Get current weather
        current = await connector.get_current()
        has_current = "error" not in current
        print_result("Get current weather", has_current)

        if has_current:
            temp = current.get("temperature", {})
            print(f"         Location: {current.get('location', {}).get('name', 'Unknown')}")
            print(f"         Temperature: {temp.get('current')}°C")
            print(f"         Humidity: {current.get('humidity', {}).get('value')}%")
            weather = current.get("weather", {})
            print(f"         Condition: {weather.get('description', 'N/A')}")

        # Get forecast
        forecast = await connector.get_forecast(days=2)
        has_forecast = "error" not in forecast
        print_result("Get forecast (2 days)", has_forecast)

        if has_forecast:
            print(f"         Forecast entries: {forecast.get('forecast_count', 0)}")

        # Disconnect
        disconnected = await connector.disconnect()
        print_result("Session cleanup", disconnected)

        return has_current and has_forecast

    except Exception as e:
        print_result("Weather test", False, str(e))
        return False


def test_sensor_processor() -> bool:
    """Test SensorProcessor"""
    print_section("SensorProcessor Test")

    try:
        # Config yükle
        device_config = get_config("devices")
        threshold_config = get_config("thresholds")

        processor = SensorProcessor(device_config, threshold_config)
        print_result("Processor initialization", True)

        # Validation tests
        valid_tests = [
            ("temperature", 25.0, True),
            ("temperature", -15.0, False),  # Out of range
            ("humidity", 65.0, True),
            ("humidity", 110.0, False),  # Over 100%
            ("soil_moisture", 50.0, True),
        ]

        all_valid = True
        for sensor_type, value, expected in valid_tests:
            result = processor.validate(sensor_type, value)
            success = result == expected
            all_valid = all_valid and success
            print_result(f"Validate {sensor_type}={value}", success,
                        f"Expected: {expected}, Got: {result}")

        # Status tests
        status_tests = [
            ("temperature", 25.0, "normal"),
            ("temperature", 14.0, "warning"),
            ("temperature", 40.0, "critical"),
            ("humidity", 70.0, "normal"),
            ("humidity", 92.0, "warning"),
            ("soil_moisture", 15.0, "critical"),
        ]

        all_status = True
        for sensor_type, value, expected in status_tests:
            result = processor.determine_status(sensor_type, value)
            success = result == expected
            all_status = all_status and success
            print_result(f"Status {sensor_type}={value}", success,
                        f"Expected: {expected}, Got: {result}")

        # Process message test
        sample_message = {
            "end_device_ids": {
                "device_id": "sera-temp-hum-01",
                "dev_eui": "0000000000000001"
            },
            "received_at": datetime.now().isoformat(),
            "uplink_message": {
                "decoded_payload": {
                    "temperature": 26.5,
                    "humidity": 68.0
                },
                "rx_metadata": [
                    {
                        "rssi": -75,
                        "snr": 8.5,
                        "gateway_ids": {"gateway_id": "test-gw-01"}
                    }
                ],
                "f_cnt": 150,
                "f_port": 1
            }
        }

        result = processor.process(sample_message)
        process_success = result is not None
        print_result("Process TTS message", process_success)

        if result:
            print(f"         Device: {result.get('device_id')}")
            print(f"         Type: {result.get('sensor_type')}")
            print(f"         Measurements: {len(result.get('measurements', []))}")
            for m in result.get("measurements", []):
                print(f"           - {m.get('name')}: {m.get('value')}{m.get('unit')} [{m.get('status')}]")

        return all_valid and all_status and process_success

    except Exception as e:
        print_result("Sensor processor test", False, str(e))
        return False


def test_trend_analyzer() -> bool:
    """Test TrendAnalyzer"""
    print_section("TrendAnalyzer Test")

    try:
        analyzer = TrendAnalyzer(window_hours=6, min_samples=3)
        print_result("Analyzer initialization", True)

        # Rising trend simulation
        print("\n  Simulating rising temperature trend...")
        base_time = datetime.now() - timedelta(hours=5)

        rising_data = [20.0, 21.5, 23.0, 24.5, 26.0, 27.5]
        for i, value in enumerate(rising_data):
            analyzer.add_sample("temperature", value, base_time + timedelta(hours=i))

        trend = analyzer.get_trend("temperature")
        rising_ok = trend.get("direction") == "rising"
        print_result("Rising trend detection", rising_ok,
                    f"Direction: {trend.get('direction')}, Rate: {trend.get('rate_formatted')}")

        # Prediction
        prediction = analyzer.predict("temperature", 2)
        pred_ok = prediction is not None and prediction.get("predicted_value", 0) > 27.5
        print_result("Prediction (2 hours ahead)", pred_ok)
        if prediction:
            print(f"         Predicted: {prediction.get('predicted_value')}°C")
            print(f"         Confidence: {prediction.get('confidence')}")

        # Summary
        summary = analyzer.get_summary("temperature")
        summary_ok = summary.get("statistics") is not None
        print_result("Summary generation", summary_ok)
        if summary_ok:
            stats = summary.get("statistics", {})
            print(f"         Min: {stats.get('min')}°C, Max: {stats.get('max')}°C")
            print(f"         Mean: {stats.get('mean'):.1f}°C")

        # Stable trend simulation
        print("\n  Simulating stable humidity trend...")
        analyzer.clear_history()

        stable_data = [65.0, 64.8, 65.2, 65.1, 64.9, 65.0]
        for i, value in enumerate(stable_data):
            analyzer.add_sample("humidity", value, base_time + timedelta(hours=i))

        trend = analyzer.get_trend("humidity")
        stable_ok = trend.get("direction") == "stable"
        print_result("Stable trend detection", stable_ok,
                    f"Direction: {trend.get('direction')}, Rate: {trend.get('rate_formatted')}")

        # Falling trend simulation
        print("\n  Simulating falling soil moisture trend...")

        falling_data = [70.0, 65.0, 60.0, 55.0, 50.0, 45.0]
        for i, value in enumerate(falling_data):
            analyzer.add_sample("soil_moisture", value, base_time + timedelta(hours=i))

        trend = analyzer.get_trend("soil_moisture")
        falling_ok = trend.get("direction") == "falling"
        print_result("Falling trend detection", falling_ok,
                    f"Direction: {trend.get('direction')}, Rate: {trend.get('rate_formatted')}")

        return rising_ok and pred_ok and stable_ok and falling_ok

    except Exception as e:
        print_result("Trend analyzer test", False, str(e))
        return False


def test_integration() -> bool:
    """Test full data processing pipeline"""
    print_section("Integration Test (Processor + Analyzer)")

    try:
        # Initialize components
        device_config = get_config("devices")
        threshold_config = get_config("thresholds")

        processor = SensorProcessor(device_config, threshold_config)
        analyzer = TrendAnalyzer(window_hours=6, min_samples=3)

        print("  Simulating sensor data stream...")

        # Simulate multiple sensor readings over time
        base_time = datetime.now() - timedelta(hours=5)
        temp_values = [22.0, 23.5, 25.0, 26.5, 28.0, 29.5]

        processed_count = 0
        for i, temp in enumerate(temp_values):
            timestamp = base_time + timedelta(hours=i)

            # Simulate TTS message
            raw_message = {
                "end_device_ids": {
                    "device_id": "sera-temp-hum-01",
                    "dev_eui": "0000000000000001"
                },
                "received_at": timestamp.isoformat(),
                "uplink_message": {
                    "decoded_payload": {
                        "temperature": temp,
                        "humidity": 65 - i * 2  # Decreasing humidity
                    }
                }
            }

            # Process message
            result = processor.process(raw_message)
            if result:
                processed_count += 1

                # Add to trend analyzer
                for m in result.get("measurements", []):
                    analyzer.add_sample(
                        m["name"],
                        m["value"],
                        timestamp
                    )

        print_result(f"Processed {processed_count}/{len(temp_values)} messages", processed_count == len(temp_values))

        # Get trends
        temp_trend = analyzer.get_trend("temperature")
        humidity_trend = analyzer.get_trend("humidity")

        print(f"\n  Temperature trend: {temp_trend.get('direction')} ({temp_trend.get('rate_formatted')})")
        print(f"  Humidity trend: {humidity_trend.get('direction')} ({humidity_trend.get('rate_formatted')})")

        # Make predictions
        temp_pred = analyzer.predict("temperature", 1)
        if temp_pred:
            print(f"\n  1-hour temperature prediction: {temp_pred.get('predicted_value')}°C")
            print(f"  Current temperature: {temp_pred.get('current_value')}°C")

        # Check final status
        last_status = processor.determine_status("temperature", temp_values[-1])
        print(f"\n  Final temperature status: {last_status}")

        success = (
            processed_count == len(temp_values) and
            temp_trend.get("direction") == "rising" and
            humidity_trend.get("direction") == "falling"
        )

        print_result("Integration pipeline", success)
        return success

    except Exception as e:
        print_result("Integration test", False, str(e))
        return False


async def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("  Sera Otonom - Data Processing Test Suite")
    print("  Phase 3: Veri İşleme")
    print("=" * 60)

    results = {
        "Weather Connector": await test_weather_connector(),
        "Sensor Processor": test_sensor_processor(),
        "Trend Analyzer": test_trend_analyzer(),
        "Integration": test_integration()
    }

    # Summary
    print_section("Test Summary")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, success in results.items():
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"  {status}: {name}")

    print(f"\n  Total: {passed}/{total} tests passed")

    if passed == total:
        print("\n  All tests passed! Phase 3 implementation complete.")
        return 0
    else:
        print("\n  Some tests failed. Please check the implementation.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
