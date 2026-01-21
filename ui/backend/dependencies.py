"""Shared dependencies for API"""

from typing import Optional
from core.brain import SeraBrain
from utils.state_manager import get_state_manager as _get_state_manager

_brain_instance: Optional[SeraBrain] = None


def set_brain_instance(brain: SeraBrain) -> None:
    """Set the brain instance (called from main.py)"""
    global _brain_instance
    _brain_instance = brain


def get_brain_instance() -> Optional[SeraBrain]:
    """Get the current brain instance"""
    return _brain_instance


def get_state_manager():
    """Get state manager instance"""
    return _get_state_manager()


def get_current_mode() -> str:
    """Get current operation mode from state"""
    try:
        state_manager = _get_state_manager()
        device_states = state_manager.read("device_states")
        return device_states.get("mode", {}).get("current", "auto")
    except Exception:
        return "auto"
