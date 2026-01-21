"""Control endpoints for mode changes and device overrides"""

from fastapi import APIRouter, HTTPException
from datetime import datetime
import logging

from ..schemas import (
    ModeRequest, ModeResponse,
    OverrideRequest, OverrideResponse,
    BrainMode
)
from ..dependencies import get_brain_instance, get_state_manager, get_current_mode

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/mode", response_model=ModeResponse)
async def set_mode(request: ModeRequest):
    """Change brain operation mode"""
    state_manager = get_state_manager()

    device_states = state_manager.read("device_states")
    previous = device_states.get("mode", {}).get("current", "auto")
    new_mode = request.mode.value

    # Update mode in state
    device_states["mode"] = {
        "current": new_mode,
        "previous": previous,
        "changed_at": datetime.utcnow().isoformat() + "Z",
        "changed_by": "api",
        "reason": request.reason
    }
    state_manager.write("device_states", device_states)

    # Determine message
    messages = {
        "auto": "Auto mode - AI making decisions",
        "manual": "Manual mode - AI disabled, manual control only",
        "paused": "Paused mode - all operations suspended"
    }

    logger.info(f"Mode changed: {previous} -> {new_mode}")

    return ModeResponse(
        success=True,
        previous_mode=BrainMode(previous),
        current_mode=BrainMode(new_mode),
        message=messages.get(new_mode, f"Mode set to {new_mode}")
    )


@router.post("/override", response_model=OverrideResponse)
async def manual_override(request: OverrideRequest):
    """Manual device control (override AI)"""
    brain = get_brain_instance()
    current_mode = get_current_mode()

    # Check if mode allows overrides
    if current_mode == "paused":
        raise HTTPException(status_code=403, detail="Overrides blocked in paused mode")

    if not brain or not brain.relay_controller:
        raise HTTPException(status_code=503, detail="Relay controller not available")

    try:
        reason = f"manual_override: {request.reason}" if request.reason else "manual_override"

        if request.action == "on":
            result = await brain.relay_controller.turn_on(
                device_id=request.device,
                duration_minutes=request.duration_minutes,
                reason=reason
            )
        else:
            result = await brain.relay_controller.turn_off(
                device_id=request.device,
                reason=reason
            )

        logger.info(f"Manual override: {request.device} -> {request.action}")

        return OverrideResponse(
            success=result.success,
            device=request.device,
            action=request.action,
            message=result.message,
            error=result.error
        )

    except Exception as e:
        logger.error(f"Override failed: {e}")
        return OverrideResponse(
            success=False,
            device=request.device,
            action=request.action,
            message="Override failed",
            error=str(e)
        )
