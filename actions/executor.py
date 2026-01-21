"""
Sera Otonom - Action Executor

Pending actions'ları işleyen modül
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

from utils.state_manager import get_state_manager
from utils.config_loader import get_config_loader
from .relay_control import RelayController, RelayCommandResult

logger = logging.getLogger(__name__)


class ActionStatus(Enum):
    """Action durumları"""
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ActionResult:
    """Tek bir action işleme sonucu"""
    action_id: str
    status: ActionStatus
    device_id: Optional[str] = None
    command: Optional[str] = None
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


@dataclass
class ExecutorStats:
    """Executor istatistikleri"""
    total_processed: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    last_run: Optional[str] = None


class ActionExecutor:
    """Pending actions işleyici"""

    def __init__(self, relay_controller: RelayController, device_config: dict):
        """
        Executor'ı başlat

        Args:
            relay_controller: RelayController instance
            device_config: Cihaz config (devices.yaml içeriği)
        """
        self.relay_controller = relay_controller
        self.device_config = device_config
        self.state_manager = get_state_manager()

        # Retry settings
        self.max_retries = 3
        self.retry_delay_seconds = 30

        # Statistics
        self.stats = ExecutorStats()

        # Load interval config
        self._load_interval_config()

        logger.info("ActionExecutor initialized")

    def _load_interval_config(self) -> None:
        """Load action interval configuration from thresholds.yaml"""
        try:
            config_loader = get_config_loader()
            thresholds = config_loader.load("thresholds")
            self.interval_config = thresholds.get("action_intervals", {})
        except Exception as e:
            logger.warning(f"Could not load interval config: {e}, using defaults")
            self.interval_config = {}

        self.default_intervals = self.interval_config.get("defaults", {
            "pump": 15, "fan": 10, "default": 15
        })

    def _get_device_interval_minutes(self, device_id: str) -> int:
        """Get minimum interval for device in minutes"""
        if device_id in self.interval_config:
            return self.interval_config[device_id]
        device_type = device_id.split("_")[0] if "_" in device_id else device_id
        return self.default_intervals.get(device_type, self.default_intervals.get("default", 15))

    def _is_on_action(self, action_type: str) -> bool:
        """Check if action is ON type"""
        return action_type.endswith("_on")

    def _check_action_interval(self, device_id: str, action_type: str) -> tuple:
        """
        Check if action interval is met
        Returns: (is_allowed: bool, skip_reason: Optional[str])
        """
        # OFF aksiyonları HER ZAMAN izin verilir (güvenlik)
        if not self._is_on_action(action_type):
            return (True, None)

        try:
            device_states = self.state_manager.read("device_states")
            device_state = device_states.get("devices", {}).get(device_id, {})
        except Exception as e:
            logger.error(f"Error reading state for interval check: {e}")
            return (True, None)  # fail-open

        last_on_time_str = device_state.get("last_on_action_time")
        if not last_on_time_str:
            logger.debug(f"First ON action for {device_id}, allowing")
            return (True, None)  # İlk aksiyon

        try:
            last_on_time = datetime.fromisoformat(last_on_time_str.replace("Z", "+00:00"))
            now = datetime.utcnow().replace(tzinfo=last_on_time.tzinfo)
            elapsed_minutes = (now - last_on_time).total_seconds() / 60
            required = self._get_device_interval_minutes(device_id)

            if elapsed_minutes >= required:
                return (True, None)

            remaining = required - elapsed_minutes
            reason = f"Interval not met: {elapsed_minutes:.1f}m elapsed, requires {required}m (wait {remaining:.1f}m)"
            return (False, reason)
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid last_on_action_time: {e}")
            return (True, None)  # fail-open

    def _update_last_on_action_time(self, device_id: str) -> None:
        """Update last ON action time for device"""
        try:
            device_states = self.state_manager.read("device_states")
            if device_id in device_states.get("devices", {}):
                device_states["devices"][device_id]["last_on_action_time"] = datetime.utcnow().isoformat() + "Z"
                self.state_manager.write("device_states", device_states)
        except Exception as e:
            logger.error(f"Failed to update last_on_action_time: {e}")

    async def process_pending_actions(self) -> List[ActionResult]:
        """
        Tüm pending actions'ları işle

        Returns:
            İşlenen action sonuçları listesi
        """
        results = []

        try:
            device_states = self.state_manager.read("device_states")
            pending_actions = device_states.get("pending_actions", [])

            if not pending_actions:
                logger.debug("No pending actions to process")
                return results

            logger.info(f"Processing {len(pending_actions)} pending actions")

            # Process each action
            for action in pending_actions[:]:  # Copy list to allow modification
                result = await self.process_single_action(action)
                results.append(result)

                # Update stats
                self.stats.total_processed += 1
                if result.status == ActionStatus.COMPLETED:
                    self.stats.successful += 1
                elif result.status == ActionStatus.FAILED:
                    self.stats.failed += 1
                elif result.status == ActionStatus.SKIPPED:
                    self.stats.skipped += 1

            self.stats.last_run = datetime.utcnow().isoformat() + "Z"
            logger.info(f"Processed {len(results)} actions: {self.stats.successful} success, {self.stats.failed} failed, {self.stats.skipped} skipped")

        except Exception as e:
            logger.error(f"Error processing pending actions: {e}")

        return results

    async def process_single_action(self, action: Dict[str, Any]) -> ActionResult:
        """
        Tek bir action'ı işle

        Args:
            action: Action dictionary

        Returns:
            ActionResult
        """
        action_id = action.get("id", "unknown")
        action_type = action.get("action", "")
        device_id = action.get("device")

        logger.debug(f"Processing action {action_id}: {action_type} for {device_id}")

        # Interval check for ON actions
        if device_id and self._is_on_action(action_type):
            is_allowed, skip_reason = self._check_action_interval(device_id, action_type)
            if not is_allowed:
                logger.warning(f"Action {action_id} SKIPPED for {device_id}: {skip_reason}")
                self._update_action_status(action_id, ActionStatus.SKIPPED, error=skip_reason)
                self._remove_action(action_id)
                return ActionResult(
                    action_id=action_id,
                    status=ActionStatus.SKIPPED,
                    device_id=device_id,
                    command=action_type,
                    error=skip_reason
                )

        # Update status to executing
        self._update_action_status(action_id, ActionStatus.EXECUTING)

        try:
            # Route to appropriate handler
            if action_type == "pump_on":
                result = await self._execute_pump_on(action)
            elif action_type == "pump_off":
                result = await self._execute_pump_off(action)
            elif action_type == "fan_on":
                result = await self._execute_fan_on(action)
            elif action_type == "fan_off":
                result = await self._execute_fan_off(action)
            elif action_type == "none":
                # No action needed, just mark as completed
                self._update_action_status(action_id, ActionStatus.COMPLETED)
                self._remove_action(action_id)
                return ActionResult(
                    action_id=action_id,
                    status=ActionStatus.SKIPPED,
                    device_id=device_id,
                    command=action_type
                )
            else:
                # Unknown action type
                logger.warning(f"Unknown action type: {action_type}")
                self._update_action_status(action_id, ActionStatus.FAILED, error=f"Unknown action: {action_type}")
                self._remove_action(action_id)
                return ActionResult(
                    action_id=action_id,
                    status=ActionStatus.FAILED,
                    device_id=device_id,
                    error=f"Unknown action type: {action_type}"
                )

            # Process result
            if result.success:
                self._update_action_status(action_id, ActionStatus.COMPLETED)
                self._remove_action(action_id)
                return ActionResult(
                    action_id=action_id,
                    status=ActionStatus.COMPLETED,
                    device_id=device_id,
                    command=action_type
                )
            else:
                # Check retry count
                retry_count = action.get("retry_count", 0)
                if retry_count < self.max_retries:
                    # Increment retry count and keep as pending
                    self._update_action_retry(action_id, retry_count + 1)
                    logger.warning(f"Action {action_id} failed, retry {retry_count + 1}/{self.max_retries}")
                    return ActionResult(
                        action_id=action_id,
                        status=ActionStatus.PENDING,
                        device_id=device_id,
                        error=result.error
                    )
                else:
                    # Max retries exceeded
                    self._update_action_status(action_id, ActionStatus.FAILED, error=result.error)
                    self._remove_action(action_id)
                    logger.error(f"Action {action_id} failed after {self.max_retries} retries: {result.error}")
                    return ActionResult(
                        action_id=action_id,
                        status=ActionStatus.FAILED,
                        device_id=device_id,
                        error=result.error
                    )

        except Exception as e:
            logger.error(f"Exception processing action {action_id}: {e}")
            self._update_action_status(action_id, ActionStatus.FAILED, error=str(e))
            self._remove_action(action_id)
            return ActionResult(
                action_id=action_id,
                status=ActionStatus.FAILED,
                device_id=device_id,
                error=str(e)
            )

    async def _execute_pump_on(self, action: Dict[str, Any]) -> RelayCommandResult:
        """Pump açma komutu"""
        device_id = action.get("device", "pump_01")
        duration = action.get("duration_minutes")
        reason = action.get("reason", "executor_triggered")

        result = await self.relay_controller.turn_on(
            device_id=device_id,
            duration_minutes=duration,
            reason=reason
        )

        # Update last ON action time on success
        if result.success:
            self._update_last_on_action_time(device_id)

        return result

    async def _execute_pump_off(self, action: Dict[str, Any]) -> RelayCommandResult:
        """Pump kapatma komutu"""
        device_id = action.get("device", "pump_01")
        reason = action.get("reason", "executor_triggered")

        return await self.relay_controller.turn_off(
            device_id=device_id,
            reason=reason
        )

    async def _execute_fan_on(self, action: Dict[str, Any]) -> RelayCommandResult:
        """Fan açma komutu"""
        device_id = action.get("device", "fan_01")
        duration = action.get("duration_minutes")
        reason = action.get("reason", "executor_triggered")

        result = await self.relay_controller.turn_on(
            device_id=device_id,
            duration_minutes=duration,
            reason=reason
        )

        # Update last ON action time on success
        if result.success:
            self._update_last_on_action_time(device_id)

        return result

    async def _execute_fan_off(self, action: Dict[str, Any]) -> RelayCommandResult:
        """Fan kapatma komutu"""
        device_id = action.get("device", "fan_01")
        reason = action.get("reason", "executor_triggered")

        return await self.relay_controller.turn_off(
            device_id=device_id,
            reason=reason
        )

    def _update_action_status(
        self,
        action_id: str,
        status: ActionStatus,
        error: Optional[str] = None
    ) -> None:
        """
        Action durumunu güncelle

        Args:
            action_id: Action ID
            status: Yeni durum
            error: Hata mesajı (varsa)
        """
        try:
            device_states = self.state_manager.read("device_states")
            pending_actions = device_states.get("pending_actions", [])

            for action in pending_actions:
                if action.get("id") == action_id:
                    action["status"] = status.value
                    action["last_updated"] = datetime.utcnow().isoformat() + "Z"
                    if error:
                        action["error"] = error
                    break

            self.state_manager.write("device_states", device_states)

        except Exception as e:
            logger.error(f"Failed to update action status: {e}")

    def _update_action_retry(self, action_id: str, retry_count: int) -> None:
        """
        Action retry sayısını güncelle

        Args:
            action_id: Action ID
            retry_count: Yeni retry sayısı
        """
        try:
            device_states = self.state_manager.read("device_states")
            pending_actions = device_states.get("pending_actions", [])

            for action in pending_actions:
                if action.get("id") == action_id:
                    action["retry_count"] = retry_count
                    action["status"] = ActionStatus.PENDING.value
                    action["last_updated"] = datetime.utcnow().isoformat() + "Z"
                    break

            self.state_manager.write("device_states", device_states)

        except Exception as e:
            logger.error(f"Failed to update action retry: {e}")

    def _remove_action(self, action_id: str) -> None:
        """
        Action'ı pending listesinden kaldır

        Args:
            action_id: Kaldırılacak action ID
        """
        try:
            device_states = self.state_manager.read("device_states")
            pending_actions = device_states.get("pending_actions", [])

            device_states["pending_actions"] = [
                a for a in pending_actions if a.get("id") != action_id
            ]

            self.state_manager.write("device_states", device_states)
            logger.debug(f"Removed action {action_id} from pending list")

        except Exception as e:
            logger.error(f"Failed to remove action: {e}")

    async def check_scheduled_shutoffs(self) -> List[str]:
        """
        Zamanlanmış kapanışları kontrol et ve geçmişte kalanları tetikle

        Returns:
            Tetiklenen cihaz ID'leri listesi
        """
        triggered = []
        now = datetime.utcnow()

        try:
            device_states = self.state_manager.read("device_states")
            devices = device_states.get("devices", {})

            for device_id, device_state in devices.items():
                scheduled_off = device_state.get("scheduled_off")
                if scheduled_off and device_state.get("state") == "on":
                    try:
                        scheduled_time = datetime.fromisoformat(scheduled_off.replace("Z", "+00:00"))
                        if now.replace(tzinfo=scheduled_time.tzinfo) >= scheduled_time:
                            logger.info(f"Scheduled shutoff triggered for {device_id}")
                            await self.relay_controller.turn_off(device_id, reason="scheduled_shutoff")
                            triggered.append(device_id)
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Invalid scheduled_off time for {device_id}: {e}")

        except Exception as e:
            logger.error(f"Error checking scheduled shutoffs: {e}")

        return triggered

    async def reset_daily_counters(self) -> None:
        """Günlük sayaçları sıfırla (gece yarısında çağrılır)"""
        try:
            device_states = self.state_manager.read("device_states")
            devices = device_states.get("devices", {})

            for device_id, device_state in devices.items():
                device_state["total_on_time_today_minutes"] = 0

            device_states["timestamp"] = datetime.utcnow().isoformat() + "Z"
            self.state_manager.write("device_states", device_states)
            logger.info("Daily counters reset")

        except Exception as e:
            logger.error(f"Failed to reset daily counters: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Executor istatistiklerini al"""
        return {
            "total_processed": self.stats.total_processed,
            "successful": self.stats.successful,
            "failed": self.stats.failed,
            "skipped": self.stats.skipped,
            "last_run": self.stats.last_run
        }

    def get_pending_count(self) -> int:
        """Bekleyen action sayısını al"""
        try:
            device_states = self.state_manager.read("device_states")
            return len(device_states.get("pending_actions", []))
        except Exception:
            return 0


if __name__ == "__main__":
    import asyncio

    async def test():
        print("ActionExecutor Test")
        print("=" * 50)

        # Create executor with mock controller
        relay_controller = RelayController(None, {
            "relays": {
                "pump_01": {"max_on_duration_minutes": 60},
                "fan_01": {"max_on_duration_minutes": 120}
            }
        })

        executor = ActionExecutor(relay_controller, {
            "relays": {
                "pump_01": {"max_on_duration_minutes": 60},
                "fan_01": {"max_on_duration_minutes": 120}
            }
        })

        # Check initial stats
        print(f"\nInitial stats: {executor.get_stats()}")
        print(f"Pending count: {executor.get_pending_count()}")

        # Process pending actions (should be empty)
        results = await executor.process_pending_actions()
        print(f"\nProcessed {len(results)} actions")

        # Shutdown
        await relay_controller.shutdown()
        print("\nTest complete")

    asyncio.run(test())
