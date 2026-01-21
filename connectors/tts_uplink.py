"""
Sera Otonom - TTS Uplink Connector

DEPRECATED: Use TTSMQTTConnector instead.
This file is kept for backwards compatibility.
"""

from .tts_mqtt import TTSMQTTConnector

# Alias for backwards compatibility
TTSUplinkConnector = TTSMQTTConnector

__all__ = ['TTSUplinkConnector', 'TTSMQTTConnector']
