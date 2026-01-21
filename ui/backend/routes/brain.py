"""Brain status and history endpoints"""

from fastapi import APIRouter, HTTPException, Query
from typing import List
from datetime import datetime

from ..schemas import (
    BrainStatus, Decision, Thought, DeviceStatus,
    DeviceState, BrainMode, AskRequest, AskResponse
)
from ..dependencies import get_brain_instance, get_state_manager, get_current_mode

router = APIRouter()


@router.get("/status", response_model=BrainStatus)
async def get_brain_status():
    """Get current brain status"""
    brain = get_brain_instance()
    state_manager = get_state_manager()

    # Get brain status dict
    status = brain.get_status() if brain else {}

    # Get device states
    device_states_data = state_manager.read("device_states")
    devices = []
    for device_id, device_data in device_states_data.get("devices", {}).items():
        devices.append(DeviceStatus(
            device_id=device_id,
            state=DeviceState(device_data.get("state", "unknown")),
            last_changed=device_data.get("last_changed"),
            scheduled_off=device_data.get("scheduled_off"),
            total_on_today_minutes=device_data.get("total_on_time_today_minutes", 0)
        ))

    return BrainStatus(
        is_running=status.get("is_running", False),
        initialized=status.get("initialized", False),
        mode=BrainMode(get_current_mode()),
        cycle_count=status.get("cycle_count", 0),
        last_cycle_time=status.get("last_cycle_time"),
        use_claude=status.get("use_claude", False),
        use_fallback=status.get("use_fallback", True),
        dry_run=status.get("dry_run", False),
        config=status.get("config", {}),
        last_decision=status.get("last_decision"),
        devices=devices,
        pending_actions=status.get("pending_actions", 0),
        executor=status.get("executor"),
        mqtt=status.get("mqtt"),
        weather=status.get("weather")
    )


@router.get("/decisions", response_model=List[Decision])
async def get_decisions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0)
):
    """Get decision history"""
    state_manager = get_state_manager()
    decisions_data = state_manager.read("decisions")

    all_decisions = decisions_data.get("decisions", [])
    all_decisions = sorted(all_decisions, key=lambda x: x.get("timestamp", ""), reverse=True)

    paginated = all_decisions[offset:offset + limit]

    return [Decision(**d) for d in paginated]


@router.get("/decisions/{decision_id}", response_model=Decision)
async def get_decision(decision_id: str):
    """Get a specific decision by ID"""
    state_manager = get_state_manager()
    decisions_data = state_manager.read("decisions")

    for d in decisions_data.get("decisions", []):
        if d.get("id") == decision_id:
            return Decision(**d)

    raise HTTPException(status_code=404, detail="Decision not found")


@router.get("/thoughts", response_model=List[Thought])
async def get_thoughts(limit: int = Query(default=10, ge=1, le=50)):
    """Get recent AI thoughts/reasoning"""
    state_manager = get_state_manager()
    thoughts_data = state_manager.read("thoughts")

    all_thoughts = thoughts_data.get("thoughts", [])
    all_thoughts = sorted(all_thoughts, key=lambda x: x.get("timestamp", ""), reverse=True)

    return [Thought(**t) for t in all_thoughts[:limit]]


@router.post("/ask", response_model=AskResponse)
async def ask_brain(request: AskRequest):
    """Ask AI a question (placeholder - not yet implemented)"""
    return AskResponse(
        success=False,
        question=request.question,
        answer=None,
        error="AI Q&A feature is not yet implemented"
    )
