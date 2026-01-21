#!/usr/bin/env python3
"""
TTS MQTT Bağlantı Test Script

Bu script TTS MQTT bağlantısını test eder (uplink subscribe + downlink publish).
Kullanım: python scripts/test_tts_connection.py
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.config_loader import get_config_loader
from utils.state_manager import get_state_manager
from connectors.tts_mqtt import TTSMQTTConnector

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)
logger = logging.getLogger(__name__)


async def test_config():
    """Config yükleme testi"""
    print("\n" + "="*50)
    print("CONFIG TEST")
    print("="*50)

    try:
        loader = get_config_loader()
        settings = loader.load('settings')
        devices = loader.load('devices')

        print(f"  Settings loaded: {settings.get('app', {}).get('name')}")
        print(f"  Devices loaded: {len(devices.get('sensors', {}))} sensors, {len(devices.get('relays', {}))} relays")

        mqtt = settings.get('tts', {}).get('mqtt', {})
        print(f"   MQTT Broker: {mqtt.get('broker')}")
        print(f"   App ID: {mqtt.get('app_id')}")

        return True
    except Exception as e:
        print(f"  Config error: {e}")
        return False


async def test_state():
    """State yönetimi testi"""
    print("\n" + "="*50)
    print("STATE TEST")
    print("="*50)

    try:
        manager = get_state_manager()

        current = manager.read('current')
        print(f"  Current state loaded")
        print(f"   Sensors: {list(current.get('sensors', {}).keys())}")

        # Test update
        manager.set('current', 'test_key', 'test_value')
        value = manager.get('current', 'test_key')
        assert value == 'test_value'
        print(f"  State update working")

        # Cleanup
        state = manager.read('current')
        state.pop('test_key', None)
        manager.write('current', state)

        return True
    except Exception as e:
        print(f"  State error: {e}")
        return False


async def test_mqtt_connection():
    """MQTT bağlantı testi"""
    print("\n" + "="*50)
    print("MQTT CONNECTION TEST")
    print("="*50)

    try:
        loader = get_config_loader()
        settings = loader.load('settings')
        mqtt_config = settings.get('tts', {}).get('mqtt', {})

        # Check credentials
        if '${' in str(mqtt_config.get('username', '')):
            print("  [WARN] MQTT credentials not configured in .env")
            print("   Set TTS_MQTT_USERNAME and TTS_MQTT_PASSWORD")
            return False

        connector = TTSMQTTConnector(mqtt_config)

        print(f"   Broker: {connector.broker}:{connector.port}")
        print(f"   App ID: {connector.app_id}")
        print(f"   Uplink topic: {connector._get_uplink_topic()}")
        print(f"   Downlink topic: {connector._get_downlink_topic('test-device')}")

        print(f"\n   Connecting...")
        connected = await connector.connect()

        if connected:
            print(f"  MQTT connected!")

            # Subscribe test
            print(f"   Subscribing to uplink...")
            await connector.subscribe()
            print(f"  Subscribed to all devices")

            health = await connector.health_check()
            print(f"   Stats: {health.get('stats')}")

            await connector.disconnect()
            print(f"  MQTT disconnected cleanly")
            return True
        else:
            print(f"  MQTT connection failed")
            return False

    except Exception as e:
        print(f"  MQTT error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_message_parsing():
    """Mesaj parse testi"""
    print("\n" + "="*50)
    print("MESSAGE PARSING TEST")
    print("="*50)

    sample_message = {
        'device_id': 'sera-temp-hum-01',
        'topic': 'v3/sera-app/devices/sera-temp-hum-01/up',
        'received_at': '2025-01-21T10:00:00Z',
        'payload': {
            'end_device_ids': {
                'device_id': 'sera-temp-hum-01',
                'dev_eui': '0011223344556677',
                'application_ids': {'application_id': 'sera-app'}
            },
            'received_at': '2025-01-21T10:00:00Z',
            'uplink_message': {
                'decoded_payload': {
                    'temperature': 24.5,
                    'humidity': 68
                },
                'f_port': 1,
                'f_cnt': 1234,
                'rx_metadata': [{
                    'rssi': -75,
                    'snr': 8.5,
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

    try:
        parsed = TTSMQTTConnector.parse_uplink_message(sample_message)

        print(f"  Uplink message parsed")
        print(f"   Device: {parsed['device_id']}")
        print(f"   DEV EUI: {parsed['dev_eui']}")
        print(f"   Decoded: {parsed['decoded_payload']}")
        print(f"   RSSI: {parsed['rssi']} dBm, SNR: {parsed['snr']} dB")

        return True
    except Exception as e:
        print(f"  Parse error: {e}")
        return False


async def test_downlink_payload():
    """Downlink payload oluşturma testi"""
    print("\n" + "="*50)
    print("DOWNLINK PAYLOAD TEST")
    print("="*50)

    try:
        # ON payload
        on_payload = TTSMQTTConnector.create_relay_payload(True)
        print(f"   ON payload:  {on_payload} (decoded: {TTSMQTTConnector.decode_payload(on_payload).hex()})")

        # OFF payload
        off_payload = TTSMQTTConnector.create_relay_payload(False)
        print(f"   OFF payload: {off_payload} (decoded: {TTSMQTTConnector.decode_payload(off_payload).hex()})")

        # Custom payload
        custom = TTSMQTTConnector.encode_payload(bytes([0x01, 0x02, 0x03]))
        print(f"   Custom:      {custom}")

        print(f"  Payload encoding working")
        return True
    except Exception as e:
        print(f"  Payload error: {e}")
        return False


async def test_downlink_dry_run():
    """Downlink gönderme testi (dry run - bağlantı gerekli değil)"""
    print("\n" + "="*50)
    print("DOWNLINK DRY RUN TEST")
    print("="*50)

    try:
        loader = get_config_loader()
        devices = loader.load('devices')

        # Check relay config
        relays = devices.get('relays', {})
        print(f"   Available relays: {list(relays.keys())}")

        for relay_id, relay_config in relays.items():
            print(f"\n   {relay_id}:")
            print(f"     TTS device_id: {relay_config.get('device_id')}")
            print(f"     Downlink port: {relay_config.get('downlink_port')}")
            print(f"     ON command:    {relay_config.get('commands', {}).get('on')}")
            print(f"     OFF command:   {relay_config.get('commands', {}).get('off')}")

        print(f"\n  Downlink config ready")
        return True
    except Exception as e:
        print(f"  Downlink config error: {e}")
        return False


async def main():
    """Ana test fonksiyonu"""
    print("\n" + "="*50)
    print("SERA OTONOM - TTS MQTT TESTS")
    print("="*50)

    results = {
        'config': await test_config(),
        'state': await test_state(),
        'parsing': await test_message_parsing(),
        'downlink_payload': await test_downlink_payload(),
        'downlink_config': await test_downlink_dry_run(),
        'mqtt': await test_mqtt_connection()
    }

    # Summary
    print("\n" + "="*50)
    print("TEST SUMMARY")
    print("="*50)

    for test, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"   {test.upper()}: {status}")

    all_passed = all(results.values())
    print("\n" + ("All tests passed!" if all_passed else "[WARN] Some tests failed"))

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
