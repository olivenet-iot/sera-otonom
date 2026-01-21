"""
Sera Otonom - TTS Downlink Connector

DEPRECATED: Use TTSMQTTConnector instead.
This file is kept for backwards compatibility.
"""

from .tts_mqtt import TTSMQTTConnector

# Alias for backwards compatibility
TTSDownlinkConnector = TTSMQTTConnector

__all__ = ['TTSDownlinkConnector', 'TTSMQTTConnector']
