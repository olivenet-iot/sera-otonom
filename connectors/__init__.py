"""
Sera Otonom - Connectors
Dış sistemlerle iletişim modülleri
"""

from .base import BaseConnector
from .tts_mqtt import TTSMQTTConnector, DownlinkResult
from .weather import WeatherConnector

# Backwards compatibility
TTSUplinkConnector = TTSMQTTConnector
TTSDownlinkConnector = TTSMQTTConnector

__all__ = [
    'BaseConnector',
    'TTSMQTTConnector',
    'TTSUplinkConnector',
    'TTSDownlinkConnector',
    'DownlinkResult',
    'WeatherConnector'
]
