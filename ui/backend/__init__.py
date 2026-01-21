"""
Sera Otonom - UI Backend
FastAPI tabanlı REST API ve WebSocket sunucusu
"""

from .main import app
from .dependencies import set_brain_instance, get_brain_instance
from .schemas import BrainMode, BrainStatus

__all__ = ["app", "set_brain_instance", "get_brain_instance", "BrainMode", "BrainStatus"]
