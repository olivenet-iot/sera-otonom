"""
Sera Otonom - TTS MQTT Connector

Tek MQTT bağlantısı üzerinden hem uplink (sensör verisi) hem downlink (relay komutları)
"""

import json
import logging
import asyncio
import ssl
import base64
from typing import Callable, Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass

import aiomqtt

from .base import BaseConnector

logger = logging.getLogger(__name__)


@dataclass
class DownlinkResult:
    """Downlink gönderim sonucu"""
    success: bool
    device_id: str
    timestamp: str
    message: Optional[str] = None
    error: Optional[str] = None


class TTSMQTTConnector(BaseConnector):
    """
    TTS MQTT Connector - Uplink & Downlink

    Uplink Topic:  v3/{app_id}/devices/{dev_id}/up
    Downlink Topic: v3/{app_id}/devices/{dev_id}/down/push
    """

    def __init__(self, config: Dict[str, Any]):
        """
        TTS MQTT connector'ı başlat

        Args:
            config: MQTT config dict:
                - broker: MQTT broker adresi
                - port: MQTT port (8883 for TLS)
                - username: MQTT username (app-id@ttn)
                - password: MQTT password (API key)
                - app_id: TTS application ID
                - use_tls: TLS kullan mı?
                - keepalive: Keepalive süresi (saniye)
                - qos: Quality of Service (0, 1, 2)
        """
        super().__init__("tts_mqtt")
        self.config = config
        self.client: Optional[aiomqtt.Client] = None
        self._message_callback: Optional[Callable] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._client_lock = asyncio.Lock()

        # Extract config values
        self.broker = config.get('broker', 'eu1.cloud.thethings.network')
        self.port = config.get('port', 8883)
        self.username = config.get('username', '')
        self.password = config.get('password', '')
        self.app_id = config.get('app_id', '')
        self.use_tls = config.get('use_tls', True)
        self.keepalive = config.get('keepalive', 60)
        self.qos = config.get('qos', 1)

        # Stats
        self.stats = {
            'uplinks_received': 0,
            'downlinks_sent': 0,
            'downlinks_success': 0,
            'downlinks_failed': 0,
            'last_uplink_time': None,
            'last_downlink_time': None,
            'errors': 0,
            'reconnects': 0
        }

    # ==================== CONNECTION ====================

    def _get_ssl_context(self) -> Optional[ssl.SSLContext]:
        """TLS için SSL context oluştur"""
        if not self.use_tls:
            return None

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        return ssl_context

    async def connect(self) -> bool:
        """MQTT broker'a bağlan"""
        try:
            logger.info(f"Connecting to MQTT broker: {self.broker}:{self.port}")

            self.client = aiomqtt.Client(
                hostname=self.broker,
                port=self.port,
                username=self.username,
                password=self.password,
                tls_context=self._get_ssl_context(),
                keepalive=self.keepalive
            )

            await self.client.__aenter__()
            self.is_connected = True
            logger.info("MQTT connected successfully")
            return True

        except Exception as e:
            logger.error(f"MQTT connection failed: {e}")
            self.stats['errors'] += 1
            self.is_connected = False
            return False

    async def disconnect(self) -> bool:
        """MQTT bağlantısını kapat"""
        try:
            self._stop_event.set()

            if self._receive_task:
                self._receive_task.cancel()
                try:
                    await self._receive_task
                except asyncio.CancelledError:
                    pass

            if self.client:
                await self.client.__aexit__(None, None, None)
                self.client = None

            self.is_connected = False
            logger.info("MQTT disconnected")
            return True

        except Exception as e:
            logger.error(f"MQTT disconnect error: {e}")
            return False

    async def health_check(self) -> Dict[str, Any]:
        """MQTT bağlantı durumunu kontrol et"""
        return {
            'connected': self.is_connected,
            'broker': self.broker,
            'app_id': self.app_id,
            'stats': self.stats,
            'last_check': datetime.utcnow().isoformat()
        }

    # ==================== TOPICS ====================

    def _get_uplink_topic(self, device_id: Optional[str] = None) -> str:
        """
        Uplink MQTT topic

        Args:
            device_id: Spesifik cihaz ID (None ise tüm cihazlar: +)
        """
        dev = device_id if device_id else "+"
        return f"v3/{self.app_id}/devices/{dev}/up"

    def _get_downlink_topic(self, device_id: str) -> str:
        """
        Downlink MQTT topic

        Args:
            device_id: Hedef cihaz ID
        """
        return f"v3/{self.app_id}/devices/{device_id}/down/push"

    # ==================== UPLINK (Receive) ====================

    async def subscribe(self, device_ids: Optional[List[str]] = None) -> None:
        """
        Uplink topic'lerine subscribe ol

        Args:
            device_ids: Subscribe olunacak cihaz ID'leri (None ise tümü)
        """
        if not self.client or not self.is_connected:
            raise ConnectionError("MQTT not connected")

        if device_ids:
            for device_id in device_ids:
                topic = self._get_uplink_topic(device_id)
                await self.client.subscribe(topic, qos=self.qos)
                logger.info(f"Subscribed to: {topic}")
        else:
            topic = self._get_uplink_topic()
            await self.client.subscribe(topic, qos=self.qos)
            logger.info(f"Subscribed to: {topic}")

    def on_message(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """
        Uplink mesajı geldiğinde çağrılacak callback'i ayarla

        Args:
            callback: Mesaj işleyici fonksiyon
                Signature: callback(parsed_message: dict) -> None
        """
        self._message_callback = callback

    async def start_listening(self) -> None:
        """Uplink mesaj dinlemeye başla"""
        if not self.client or not self.is_connected:
            raise ConnectionError("MQTT not connected")

        self._stop_event.clear()
        self._receive_task = asyncio.create_task(self._message_loop())
        logger.info("Started listening for uplink messages")

    async def stop_listening(self) -> None:
        """Uplink mesaj dinlemeyi durdur"""
        self._stop_event.set()
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        logger.info("Stopped listening for uplink messages")

    async def _message_loop(self) -> None:
        """Uplink mesaj alma döngüsü"""
        try:
            async for message in self.client.messages:
                if self._stop_event.is_set():
                    break

                try:
                    # Parse message
                    payload = json.loads(message.payload.decode())

                    # Extract device info from topic
                    topic_parts = str(message.topic).split('/')
                    device_id = topic_parts[3] if len(topic_parts) > 3 else None

                    parsed = {
                        'device_id': device_id,
                        'topic': str(message.topic),
                        'received_at': datetime.utcnow().isoformat(),
                        'payload': payload
                    }

                    # Update stats
                    self.stats['uplinks_received'] += 1
                    self.stats['last_uplink_time'] = parsed['received_at']

                    logger.debug(f"Received uplink from {device_id}")

                    # Call callback
                    if self._message_callback:
                        try:
                            await self._async_callback(parsed)
                        except Exception as e:
                            logger.error(f"Callback error: {e}")
                            self.stats['errors'] += 1

                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error: {e}")
                    self.stats['errors'] += 1
                except Exception as e:
                    logger.error(f"Message processing error: {e}")
                    self.stats['errors'] += 1

        except asyncio.CancelledError:
            logger.info("Message loop cancelled")
        except Exception as e:
            logger.error(f"Message loop error: {e}")
            self.stats['errors'] += 1

    async def _async_callback(self, message: Dict[str, Any]) -> None:
        """Callback'i async olarak çağır"""
        if asyncio.iscoroutinefunction(self._message_callback):
            await self._message_callback(message)
        else:
            self._message_callback(message)

    # ==================== DOWNLINK (Send) ====================

    async def send_downlink(
        self,
        device_id: str,
        payload: str,
        port: int = 1,
        confirmed: bool = False,
        priority: str = "NORMAL"
    ) -> DownlinkResult:
        """
        Downlink mesajı gönder (MQTT publish)

        Args:
            device_id: Hedef cihaz ID (TTS device_id)
            payload: Base64 encoded payload
            port: FPort (1-223)
            confirmed: Onaylı mı (ACK beklenir)?
            priority: Öncelik (LOWEST, LOW, BELOW_NORMAL, NORMAL, ABOVE_NORMAL, HIGH, HIGHEST)

        Returns:
            DownlinkResult
        """
        if not self.client or not self.is_connected:
            return DownlinkResult(
                success=False,
                device_id=device_id,
                timestamp=datetime.utcnow().isoformat(),
                error="MQTT not connected"
            )

        topic = self._get_downlink_topic(device_id)

        # TTS downlink payload formatı
        downlink_message = {
            "downlinks": [{
                "frm_payload": payload,
                "f_port": port,
                "priority": priority,
                "confirmed": confirmed
            }]
        }

        logger.info(f"Sending downlink to {device_id} on topic {topic}")
        logger.debug(f"Downlink payload: {downlink_message}")

        try:
            async with self._client_lock:
                await self.client.publish(
                    topic=topic,
                    payload=json.dumps(downlink_message),
                    qos=self.qos
                )

            # Update stats
            self.stats['downlinks_sent'] += 1
            self.stats['downlinks_success'] += 1
            self.stats['last_downlink_time'] = datetime.utcnow().isoformat()

            logger.info(f"Downlink sent successfully to {device_id}")

            return DownlinkResult(
                success=True,
                device_id=device_id,
                timestamp=self.stats['last_downlink_time'],
                message="Downlink published successfully"
            )

        except Exception as e:
            self.stats['downlinks_sent'] += 1
            self.stats['downlinks_failed'] += 1
            logger.error(f"Downlink failed: {e}")

            return DownlinkResult(
                success=False,
                device_id=device_id,
                timestamp=datetime.utcnow().isoformat(),
                error=str(e)
            )

    async def send_relay_command(
        self,
        device_id: str,
        command: str,
        device_config: Dict[str, Any]
    ) -> DownlinkResult:
        """
        Yüksek seviye relay komutu gönder

        Args:
            device_id: Cihaz ID (config key, örn: "pump_01")
            command: Komut ("on" veya "off")
            device_config: devices.yaml içeriği

        Returns:
            DownlinkResult
        """
        # Get relay config
        relay_config = device_config.get('relays', {}).get(device_id, {})

        if not relay_config:
            return DownlinkResult(
                success=False,
                device_id=device_id,
                timestamp=datetime.utcnow().isoformat(),
                error=f"Relay config not found: {device_id}"
            )

        # Get command payload (base64)
        commands = relay_config.get('commands', {})
        payload = commands.get(command)

        if not payload:
            return DownlinkResult(
                success=False,
                device_id=device_id,
                timestamp=datetime.utcnow().isoformat(),
                error=f"Command not found: {command}"
            )

        # Get TTS device_id and port
        tts_device_id = relay_config.get('device_id', device_id)
        port = relay_config.get('downlink_port', 1)

        logger.info(f"Sending relay command: {device_id} -> {command}")

        return await self.send_downlink(
            device_id=tts_device_id,
            payload=payload,
            port=port,
            confirmed=True
        )

    # ==================== HELPERS ====================

    @staticmethod
    def parse_uplink_message(raw_message: Dict[str, Any]) -> Dict[str, Any]:
        """
        TTS uplink mesajını parse et

        Args:
            raw_message: Ham TTS mesajı (callback'e gelen)

        Returns:
            Normalize edilmiş mesaj
        """
        payload = raw_message.get('payload', {})

        # End device IDs
        end_device = payload.get('end_device_ids', {})

        # Uplink message
        uplink = payload.get('uplink_message', {})

        # Decoded payload (from payload formatter)
        decoded = uplink.get('decoded_payload', {})

        # RF metadata
        rx_metadata = uplink.get('rx_metadata', [{}])[0] if uplink.get('rx_metadata') else {}

        # Settings
        settings = uplink.get('settings', {}).get('data_rate', {}).get('lora', {})

        return {
            'device_id': end_device.get('device_id'),
            'dev_eui': end_device.get('dev_eui'),
            'application_id': end_device.get('application_ids', {}).get('application_id'),
            'received_at': payload.get('received_at'),
            'decoded_payload': decoded,
            'raw_payload': uplink.get('frm_payload'),
            'f_port': uplink.get('f_port'),
            'f_cnt': uplink.get('f_cnt'),
            'rssi': rx_metadata.get('rssi'),
            'snr': rx_metadata.get('snr'),
            'spreading_factor': settings.get('spreading_factor'),
            'bandwidth': settings.get('bandwidth'),
            'gateway_id': rx_metadata.get('gateway_ids', {}).get('gateway_id')
        }

    @staticmethod
    def encode_payload(data: bytes) -> str:
        """Bytes'ı base64'e encode et"""
        return base64.b64encode(data).decode('ascii')

    @staticmethod
    def decode_payload(b64_string: str) -> bytes:
        """Base64'ü bytes'a decode et"""
        return base64.b64decode(b64_string)

    @staticmethod
    def create_relay_payload(state: bool) -> str:
        """
        Relay komutu için payload oluştur

        Args:
            state: True=ON, False=OFF

        Returns:
            Base64 encoded payload
        """
        byte_value = bytes([0x01 if state else 0x00])
        return base64.b64encode(byte_value).decode('ascii')


if __name__ == "__main__":
    # Test
    import asyncio

    async def test():
        config = {
            'broker': 'eu1.cloud.thethings.network',
            'port': 8883,
            'username': 'test-app@ttn',
            'password': 'test-key',
            'app_id': 'test-app',
            'use_tls': True
        }

        connector = TTSMQTTConnector(config)
        print(f"Connector created: {connector.name}")
        print(f"Uplink topic: {connector._get_uplink_topic()}")
        print(f"Downlink topic: {connector._get_downlink_topic('test-device')}")
        print(f"Health: {await connector.health_check()}")

    asyncio.run(test())
