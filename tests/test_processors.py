"""
Sera Otonom - Processor Unit Tests
"""

import pytest
from datetime import datetime, timedelta

from processors.sensor_processor import SensorProcessor
from processors.trend_analyzer import TrendAnalyzer


# ============================================================================
# SensorProcessor Tests
# ============================================================================

class TestSensorProcessor:
    """SensorProcessor test suite"""

    @pytest.fixture
    def device_config(self):
        """Sample device config"""
        return {
            "sensors": {
                "temp_humidity_01": {
                    "device_id": "sera-temp-hum-01",
                    "type": "temperature_humidity",
                    "measurements": [
                        {
                            "name": "temperature",
                            "unit": "°C",
                            "decoded_field": "temperature",
                            "valid_range": [-10, 60]
                        },
                        {
                            "name": "humidity",
                            "unit": "%",
                            "decoded_field": "humidity",
                            "valid_range": [0, 100]
                        }
                    ],
                    "location": "sera_ic"
                },
                "soil_moisture_01": {
                    "device_id": "sera-soil-01",
                    "type": "soil_moisture",
                    "measurements": [
                        {
                            "name": "soil_moisture",
                            "unit": "%",
                            "decoded_field": "moisture",
                            "valid_range": [0, 100]
                        }
                    ],
                    "location": "sera_ic"
                }
            }
        }

    @pytest.fixture
    def threshold_config(self):
        """Sample threshold config"""
        return {
            "temperature": {
                "optimal_range": [20, 28],
                "warning_low": 15,
                "warning_high": 32,
                "critical_low": 10,
                "critical_high": 38
            },
            "humidity": {
                "optimal_range": [60, 80],
                "warning_low": 50,
                "warning_high": 90,
                "critical_low": 40,
                "critical_high": 95
            },
            "soil_moisture": {
                "optimal_range": [40, 70],
                "warning_low": 30,
                "warning_high": 80,
                "critical_low": 20,
                "critical_high": 90
            }
        }

    @pytest.fixture
    def processor(self, device_config, threshold_config):
        """Create processor instance"""
        return SensorProcessor(device_config, threshold_config)

    # --- Validation Tests ---

    def test_validate_temperature_valid(self, processor):
        """Test temperature validation with valid value"""
        assert processor.validate("temperature", 25) is True
        assert processor.validate("temperature", -5) is True
        assert processor.validate("temperature", 55) is True

    def test_validate_temperature_invalid(self, processor):
        """Test temperature validation with invalid value"""
        assert processor.validate("temperature", -20) is False
        assert processor.validate("temperature", 70) is False

    def test_validate_humidity_valid(self, processor):
        """Test humidity validation"""
        assert processor.validate("humidity", 50) is True
        assert processor.validate("humidity", 0) is True
        assert processor.validate("humidity", 100) is True

    def test_validate_invalid_type(self, processor):
        """Test validation with invalid value types"""
        assert processor.validate("temperature", "invalid") is False
        assert processor.validate("temperature", None) is False

    # --- Status Determination Tests ---

    def test_status_normal(self, processor):
        """Test normal status"""
        assert processor.determine_status("temperature", 25) == "normal"
        assert processor.determine_status("humidity", 70) == "normal"

    def test_status_warning_low(self, processor):
        """Test warning status for low values"""
        assert processor.determine_status("temperature", 14) == "warning"
        assert processor.determine_status("humidity", 45) == "warning"

    def test_status_warning_high(self, processor):
        """Test warning status for high values"""
        assert processor.determine_status("temperature", 33) == "warning"
        assert processor.determine_status("humidity", 92) == "warning"

    def test_status_critical_low(self, processor):
        """Test critical status for low values"""
        assert processor.determine_status("temperature", 8) == "critical"
        assert processor.determine_status("humidity", 35) == "critical"

    def test_status_critical_high(self, processor):
        """Test critical status for high values"""
        assert processor.determine_status("temperature", 40) == "critical"
        assert processor.determine_status("humidity", 97) == "critical"

    def test_status_unknown_for_invalid(self, processor):
        """Test unknown status for invalid values"""
        assert processor.determine_status("temperature", "invalid") == "unknown"

    def test_status_unknown_sensor_type(self, processor):
        """Test status for unknown sensor type returns normal"""
        assert processor.determine_status("unknown_sensor", 50) == "normal"

    # --- Process Message Tests ---

    def test_process_valid_message(self, processor):
        """Test processing a valid TTS message"""
        raw_message = {
            "end_device_ids": {
                "device_id": "sera-temp-hum-01",
                "dev_eui": "0000000000000001"
            },
            "received_at": "2024-01-15T10:30:00Z",
            "uplink_message": {
                "decoded_payload": {
                    "temperature": 25.5,
                    "humidity": 65.0
                },
                "rx_metadata": [
                    {
                        "rssi": -80,
                        "snr": 7.5,
                        "gateway_ids": {"gateway_id": "gw-01"}
                    }
                ],
                "f_cnt": 100,
                "f_port": 1
            }
        }

        result = processor.process(raw_message)

        assert result is not None
        assert result["device_id"] == "sera-temp-hum-01"
        assert result["sensor_type"] == "temperature_humidity"
        assert len(result["measurements"]) == 2

        temp_measurement = next(m for m in result["measurements"] if m["name"] == "temperature")
        assert temp_measurement["value"] == 25.5
        assert temp_measurement["status"] == "normal"
        assert temp_measurement["valid"] is True

    def test_process_unknown_device(self, processor):
        """Test processing message from unknown device"""
        raw_message = {
            "end_device_ids": {
                "device_id": "unknown-device",
                "dev_eui": "0000000000000000"
            },
            "uplink_message": {
                "decoded_payload": {"temperature": 25}
            }
        }

        result = processor.process(raw_message)
        assert result is None

    def test_process_missing_payload(self, processor):
        """Test processing message with missing payload"""
        raw_message = {
            "end_device_ids": {
                "device_id": "sera-temp-hum-01",
                "dev_eui": "0000000000000001"
            },
            "uplink_message": {
                "decoded_payload": {}
            }
        }

        result = processor.process(raw_message)
        assert result is None

    def test_get_status_summary(self, processor):
        """Test status summary"""
        measurements = [
            {"status": "normal"},
            {"status": "warning"},
            {"status": "normal"}
        ]
        assert processor.get_status_summary(measurements) == "warning"

        measurements = [
            {"status": "normal"},
            {"status": "critical"},
            {"status": "warning"}
        ]
        assert processor.get_status_summary(measurements) == "critical"

        measurements = [
            {"status": "normal"},
            {"status": "normal"}
        ]
        assert processor.get_status_summary(measurements) == "normal"


# ============================================================================
# TrendAnalyzer Tests
# ============================================================================

class TestTrendAnalyzer:
    """TrendAnalyzer test suite"""

    @pytest.fixture
    def analyzer(self):
        """Create analyzer instance"""
        return TrendAnalyzer(window_hours=6, min_samples=3)

    def test_add_sample(self, analyzer):
        """Test adding samples"""
        analyzer.add_sample("temperature", 25.0)
        analyzer.add_sample("temperature", 26.0)

        assert len(analyzer.history["temperature"]) == 2

    def test_trend_insufficient_samples(self, analyzer):
        """Test trend with insufficient samples"""
        analyzer.add_sample("temperature", 25.0)
        analyzer.add_sample("temperature", 26.0)

        result = analyzer.get_trend("temperature")
        assert result["direction"] == "unknown"
        assert "error" in result

    def test_trend_rising(self, analyzer):
        """Test rising trend detection"""
        base_time = datetime.now()
        for i in range(5):
            analyzer.add_sample(
                "temperature",
                20.0 + i * 2.0,  # 20, 22, 24, 26, 28
                base_time + timedelta(hours=i)
            )

        result = analyzer.get_trend("temperature")
        assert result["direction"] == "rising"
        assert result["rate"] > 0
        assert result["sample_count"] == 5

    def test_trend_falling(self, analyzer):
        """Test falling trend detection"""
        base_time = datetime.now()
        for i in range(5):
            analyzer.add_sample(
                "temperature",
                30.0 - i * 2.0,  # 30, 28, 26, 24, 22
                base_time + timedelta(hours=i)
            )

        result = analyzer.get_trend("temperature")
        assert result["direction"] == "falling"
        assert result["rate"] < 0

    def test_trend_stable(self, analyzer):
        """Test stable trend detection"""
        base_time = datetime.now()
        for i in range(5):
            analyzer.add_sample(
                "temperature",
                25.0 + (i * 0.1),  # Very small change
                base_time + timedelta(hours=i)
            )

        result = analyzer.get_trend("temperature")
        assert result["direction"] == "stable"

    def test_predict(self, analyzer):
        """Test prediction"""
        base_time = datetime.now()
        for i in range(5):
            analyzer.add_sample(
                "temperature",
                20.0 + i * 1.0,  # 20, 21, 22, 23, 24
                base_time + timedelta(hours=i)
            )

        result = analyzer.predict("temperature", 2)
        assert result is not None
        assert "predicted_value" in result
        assert result["predicted_value"] > 24  # Should be higher
        assert "confidence" in result

    def test_predict_insufficient_samples(self, analyzer):
        """Test prediction with insufficient samples"""
        analyzer.add_sample("temperature", 25.0)

        result = analyzer.predict("temperature", 2)
        assert result is None

    def test_get_summary(self, analyzer):
        """Test summary generation"""
        base_time = datetime.now()
        for i in range(5):
            analyzer.add_sample(
                "temperature",
                20.0 + i * 1.0,
                base_time + timedelta(hours=i)
            )

        result = analyzer.get_summary("temperature")
        assert result["sensor_type"] == "temperature"
        assert result["trend"]["direction"] == "rising"
        assert result["statistics"]["min"] == 20.0
        assert result["statistics"]["max"] == 24.0
        assert "predictions" in result

    def test_clear_history(self, analyzer):
        """Test clearing history"""
        analyzer.add_sample("temperature", 25.0)
        analyzer.add_sample("humidity", 65.0)

        analyzer.clear_history("temperature")
        assert "temperature" not in analyzer.history
        assert "humidity" in analyzer.history

        analyzer.clear_history()
        assert len(analyzer.history) == 0

    def test_cleanup_old_samples(self, analyzer):
        """Test automatic cleanup of old samples"""
        # Add an old sample (beyond window)
        old_time = datetime.now() - timedelta(hours=10)
        analyzer.add_sample("temperature", 20.0, old_time)

        # Add recent samples
        for i in range(3):
            analyzer.add_sample(
                "temperature",
                25.0 + i,
                datetime.now() - timedelta(hours=i)
            )

        # Old sample should be cleaned up
        assert len(analyzer.history["temperature"]) == 3

    def test_linear_regression_accuracy(self, analyzer):
        """Test linear regression calculation accuracy"""
        base_time = datetime.now()
        # Perfect linear data: y = 2x + 10
        for i in range(5):
            analyzer.add_sample(
                "temperature",
                10.0 + i * 2.0,  # 10, 12, 14, 16, 18
                base_time + timedelta(hours=i)
            )

        samples = analyzer.history["temperature"]
        slope, intercept, r_squared = analyzer._calculate_linear_regression(samples)

        assert abs(slope - 2.0) < 0.01  # Slope should be ~2
        assert abs(r_squared - 1.0) < 0.01  # Perfect fit

    def test_empty_sensor_summary(self, analyzer):
        """Test summary for sensor with no data"""
        result = analyzer.get_summary("nonexistent")
        assert result["sensor_type"] == "nonexistent"
        assert result["statistics"] is None


# ============================================================================
# Integration Tests
# ============================================================================

class TestProcessorIntegration:
    """Integration tests for processors working together"""

    def test_processor_to_analyzer_flow(self):
        """Test data flow from processor to analyzer"""
        device_config = {
            "sensors": {
                "temp_01": {
                    "device_id": "test-device",
                    "type": "temperature",
                    "measurements": [
                        {"name": "temperature", "unit": "°C", "decoded_field": "temp", "valid_range": [-10, 60]}
                    ],
                    "location": "test"
                }
            }
        }
        threshold_config = {
            "temperature": {
                "optimal_range": [20, 28],
                "warning_low": 15,
                "warning_high": 32,
                "critical_low": 10,
                "critical_high": 38
            }
        }

        processor = SensorProcessor(device_config, threshold_config)
        analyzer = TrendAnalyzer(window_hours=6, min_samples=3)

        # Simulate multiple sensor readings
        base_time = datetime.now()
        for i in range(5):
            raw_message = {
                "end_device_ids": {"device_id": "test-device", "dev_eui": "001"},
                "received_at": (base_time + timedelta(hours=i)).isoformat(),
                "uplink_message": {
                    "decoded_payload": {"temp": 20.0 + i * 1.0}
                }
            }

            result = processor.process(raw_message)
            if result:
                for m in result["measurements"]:
                    analyzer.add_sample(
                        m["name"],
                        m["value"],
                        datetime.fromisoformat(result["timestamp"].replace("Z", "+00:00").replace("+00:00", ""))
                        if "Z" in result["timestamp"] else datetime.fromisoformat(result["timestamp"])
                    )

        # Check trend
        trend = analyzer.get_trend("temperature")
        assert trend["direction"] == "rising"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
