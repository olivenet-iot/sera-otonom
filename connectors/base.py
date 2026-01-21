"""
Sera Otonom - Base Connector

Tüm connector'lar için abstract base class
"""

from abc import ABC, abstractmethod
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


class BaseConnector(ABC):
    """Abstract base connector"""

    def __init__(self, name: str):
        self.name = name
        self.is_connected = False
        logger.info(f"Connector '{name}' initialized")

    @abstractmethod
    async def connect(self) -> bool:
        """Bağlantı kur"""
        pass

    @abstractmethod
    async def disconnect(self) -> bool:
        """Bağlantıyı kapat"""
        pass

    @abstractmethod
    async def health_check(self) -> dict:
        """Bağlantı sağlığını kontrol et"""
        pass
