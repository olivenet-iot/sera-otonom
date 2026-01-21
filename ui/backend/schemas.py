"""Pydantic models for API requests and responses"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# === Enums ===

class BrainMode(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"
    PAUSED = "paused"


class DeviceState(str, Enum):
    ON = "on"
    OFF = "off"
    UNKNOWN = "unknown"


class ActionType(str, Enum):
    PUMP_ON = "pump_on"
    PUMP_OFF = "pump_off"
    FAN_ON = "fan_on"
    FAN_OFF = "fan_off"
    NONE = "none"


# === Response Models ===

class DeviceStatus(BaseModel):
    device_id: str
    state: DeviceState
    last_changed: Optional[str] = None
    scheduled_off: Optional[str] = None
    total_on_today_minutes: float = 0


class BrainStatus(BaseModel):
    """GET /api/brain/status response"""
    is_running: bool
    initialized: bool
    mode: BrainMode
    cycle_count: int = 0
    last_cycle_time: Optional[str] = None
    use_claude: bool = True
    use_fallback: bool = True
    dry_run: bool = False
    config: Dict[str, Any] = {}
    last_decision: Optional[Dict[str, Any]] = None
    devices: List[DeviceStatus] = []
    pending_actions: int = 0
    executor: Optional[Dict[str, Any]] = None
    mqtt: Optional[Dict[str, Any]] = None
    weather: Optional[Dict[str, Any]] = None


class Decision(BaseModel):
    """Decision model"""
    id: str
    timestamp: str
    cycle_id: Optional[str] = None
    decision: Dict[str, Any]
    analysis: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None
    source: str = "fallback"


class Thought(BaseModel):
    """Thought/reasoning model"""
    id: str
    timestamp: str
    cycle_id: Optional[str] = None
    reasoning: Optional[str] = None
    raw_output: Optional[str] = None


# === Request Models ===

class ModeRequest(BaseModel):
    mode: BrainMode
    reason: Optional[str] = None


class ModeResponse(BaseModel):
    success: bool
    previous_mode: BrainMode
    current_mode: BrainMode
    message: str


class OverrideRequest(BaseModel):
    device: str = Field(..., pattern=r"^(pump|fan)_\d{2}$")
    action: str = Field(..., pattern=r"^(on|off)$")
    duration_minutes: Optional[int] = Field(None, ge=1, le=120)
    reason: Optional[str] = "manual_override"


class OverrideResponse(BaseModel):
    success: bool
    device: str
    action: str
    message: Optional[str] = None
    error: Optional[str] = None


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)


class AskResponse(BaseModel):
    success: bool
    question: str
    answer: Optional[str] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = "healthy"
    timestamp: str
    version: str


class InfoResponse(BaseModel):
    version: str
    uptime_seconds: int
    brain_status: str
    mode: BrainMode
