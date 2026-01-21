"""
TTS MQTT Connector Tests
"""

import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from connectors.tts_mqtt import TTSMQTTConnector, DownlinkResult
from utils.config_loader import ConfigLoader
from utils.state_manager import StateManager


class TestConfigLoader:
    """Config Loader Tests"""

    def test_env_pattern_resolution(self):
        """Environment variable pattern çözümleme testi"""
        loader = ConfigLoader()

        with patch.dict('os.environ', {'TEST_VAR': 'test_value'}):
            result = loader._resolve_env_vars("prefix_${TEST_VAR}_suffix")
            assert result == "prefix_test_value_suffix"

    def test_nested_env_resolution(self):
        """Nested dict'lerde env var çözümleme"""
        loader = ConfigLoader()

        with patch.dict('os.environ', {'VAR1': 'value1', 'VAR2': 'value2'}):
            data = {
                'level1': {
                    'key1': '${VAR1}',
                    'level2': {
                        'key2': '${VAR2}'
                    }
                }
            }
            result = loader._resolve_env_vars(data)
            assert result['level1']['key1'] == 'value1'
            assert result['level1']['level2']['key2'] == 'value2'


class TestStateManager:
    """State Manager Tests"""

    def test_deep_merge(self, tmp_path):
        """Deep merge testi"""
        manager = StateManager(base_path=tmp_path)

        base = {'a': {'b': 1, 'c': 2}}
        updates = {'a': {'b': 10, 'd': 4}}

        manager._deep_merge(base, updates)

        assert base == {'a': {'b': 10, 'c': 2, 'd': 4}}

    def test_key_path_get(self, tmp_path):
        """Nested key path get testi"""
        manager = StateManager(base_path=tmp_path)
        state_dir = tmp_path / "state"
        state_dir.mkdir(exist_ok=True)

        test_data = {
            'level1': {
                'level2': {
                    'value': 42
                }
            }
        }

        with open(state_dir / "test.json", 'w') as f:
            json.dump(test_data, f)

        result = manager.get("test", "level1.level2.value")
        assert result == 42

        result = manager.get("test", "nonexistent.path", default="default")
        assert result == "default"


class TestTTSMQTTConnector:
    """TTS MQTT Connector Tests"""

    def test_topic_generation(self):
        """Topic string oluşturma testi"""
        config = {'app_id': 'sera-app'}
        connector = TTSMQTTConnector(config)

        # Uplink - all devices
        assert connector._get_uplink_topic() == "v3/sera-app/devices/+/up"

        # Uplink - specific device
        assert connector._get_uplink_topic("sensor-01") == "v3/sera-app/devices/sensor-01/up"

        # Downlink
        assert connector._get_downlink_topic("relay-01") == "v3/sera-app/devices/relay-01/down/push"

    def test_payload_encoding(self):
        """Payload encoding testi"""
        # ON command (0x01)
        payload = TTSMQTTConnector.create_relay_payload(True)
        assert payload == "AQ=="

        # OFF command (0x00)
        payload = TTSMQTTConnector.create_relay_payload(False)
        assert payload == "AA=="

    def test_encode_decode_roundtrip(self):
        """Encode/decode round-trip testi"""
        original = b'\x01\x02\x03\xFF'
        encoded = TTSMQTTConnector.encode_payload(original)
        decoded = TTSMQTTConnector.decode_payload(encoded)
        assert decoded == original

    def test_parse_uplink_message(self):
        """Uplink mesaj parse testi"""
        raw_message = {
            'payload': {
                'end_device_ids': {
                    'device_id': 'sera-temp-hum-01',
                    'dev_eui': '0011223344556677',
                    'application_ids': {'application_id': 'sera-app'}
                },
                'received_at': '2025-01-21T10:00:00Z',
                'uplink_message': {
                    'decoded_payload': {
                        'temperature': 25.5,
                        'humidity': 65
                    },
                    'frm_payload': 'AQID',
                    'f_port': 1,
                    'f_cnt': 100,
                    'rx_metadata': [{
                        'rssi': -80,
                        'snr': 7.5,
                        'gateway_ids': {'gateway_id': 'sera-gateway'}
                    }],
                    'settings': {
                        'data_rate': {
                            'lora': {
                                'spreading_factor': 7,
                                'bandwidth': 125000
                            }
                        }
                    }
                }
            }
        }

        parsed = TTSMQTTConnector.parse_uplink_message(raw_message)

        assert parsed['device_id'] == 'sera-temp-hum-01'
        assert parsed['dev_eui'] == '0011223344556677'
        assert parsed['decoded_payload']['temperature'] == 25.5
        assert parsed['decoded_payload']['humidity'] == 65
        assert parsed['rssi'] == -80
        assert parsed['snr'] == 7.5
        assert parsed['spreading_factor'] == 7

    @pytest.mark.asyncio
    async def test_health_check_structure(self):
        """Health check yapı testi"""
        config = {
            'broker': 'test.example.com',
            'app_id': 'test-app'
        }

        connector = TTSMQTTConnector(config)
        health = await connector.health_check()

        assert 'connected' in health
        assert 'broker' in health
        assert 'app_id' in health
        assert 'stats' in health
        assert health['broker'] == 'test.example.com'
        assert health['app_id'] == 'test-app'

    @pytest.mark.asyncio
    async def test_send_relay_command_missing_config(self):
        """Eksik config ile relay komutu testi"""
        config = {'app_id': 'test-app'}
        connector = TTSMQTTConnector(config)
        connector.is_connected = True

        result = await connector.send_relay_command(
            device_id='nonexistent',
            command='on',
            device_config={'relays': {}}
        )

        assert not result.success
        assert 'not found' in result.error

    def test_downlink_result_dataclass(self):
        """DownlinkResult dataclass testi"""
        result = DownlinkResult(
            success=True,
            device_id='pump-01',
            timestamp='2025-01-21T10:00:00Z',
            message='OK'
        )

        assert result.success
        assert result.device_id == 'pump-01'
        assert result.error is None


class TestDownlinkPayload:
    """Downlink payload format tests"""

    def test_downlink_message_format(self):
        """TTS downlink mesaj formatı testi"""
        # Expected format for MQTT publish
        expected_format = {
            "downlinks": [{
                "frm_payload": "AQ==",  # base64
                "f_port": 1,
                "priority": "NORMAL",
                "confirmed": True
            }]
        }

        # Verify it's valid JSON
        json_str = json.dumps(expected_format)
        parsed = json.loads(json_str)

        assert 'downlinks' in parsed
        assert len(parsed['downlinks']) == 1
        assert parsed['downlinks'][0]['frm_payload'] == "AQ=="


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
