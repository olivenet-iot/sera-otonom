"""
Sera Otonom - Executor Unit Tests

pytest ile executor modülü testleri
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

from actions.relay_control import RelayController, RelayCommandResult
from actions.executor import ActionExecutor, ActionStatus, ActionResult, ExecutorStats


# ==================== RelayCommandResult Tests ====================

class TestRelayCommandResult:
    """RelayCommandResult dataclass testleri"""

    def test_success_result(self):
        result = RelayCommandResult(
            success=True,
            device_id="pump_01",
            command="on",
            message="Device turned on"
        )
        assert result.success is True
        assert result.device_id == "pump_01"
        assert result.command == "on"
        assert result.error is None

    def test_error_result(self):
        result = RelayCommandResult(
            success=False,
            device_id="pump_01",
            command="on",
            error="MQTT connection failed"
        )
        assert result.success is False
        assert result.error == "MQTT connection failed"

    def test_default_timestamp(self):
        result = RelayCommandResult(
            success=True,
            device_id="pump_01",
            command="on"
        )
        assert result.timestamp is not None
        assert "T" in result.timestamp  # ISO format


# ==================== RelayController Tests ====================

class TestRelayController:
    """RelayController testleri"""

    @pytest.fixture
    def device_config(self):
        return {
            "relays": {
                "pump_01": {
                    "device_id": "sera-pump-01",
                    "max_on_duration_minutes": 60,
                    "commands": {"on": "AQ==", "off": "AA=="}
                },
                "fan_01": {
                    "device_id": "sera-fan-01",
                    "max_on_duration_minutes": 120,
                    "commands": {"on": "AQ==", "off": "AA=="}
                }
            }
        }

    @pytest.fixture
    def mock_mqtt(self):
        mqtt = Mock()
        mqtt.send_relay_command = AsyncMock(return_value=RelayCommandResult(
            success=True,
            device_id="pump_01",
            command="on",
            message="Command sent"
        ))
        return mqtt

    @pytest.fixture
    def controller(self, mock_mqtt, device_config):
        with patch('actions.relay_control.get_state_manager') as mock_sm:
            mock_sm.return_value.read.return_value = {
                "devices": {
                    "pump_01": {"state": "off", "total_on_time_today_minutes": 0},
                    "fan_01": {"state": "off", "total_on_time_today_minutes": 0}
                },
                "pending_actions": []
            }
            mock_sm.return_value.write = Mock()
            return RelayController(mock_mqtt, device_config)

    def test_init(self, controller):
        assert controller.mqtt is not None
        assert controller.device_config is not None

    @pytest.mark.asyncio
    async def test_turn_on_success(self, controller):
        result = await controller.turn_on("pump_01", duration_minutes=10, reason="test")

        assert result.success is True
        assert result.device_id == "pump_01"
        assert result.command == "on"

    @pytest.mark.asyncio
    async def test_turn_on_unknown_device(self, controller):
        result = await controller.turn_on("unknown_device")

        assert result.success is False
        assert "Unknown device" in result.error

    @pytest.mark.asyncio
    async def test_turn_on_duration_safety_limit(self, controller):
        """Duration safety limit'i test et"""
        # pump_01 max 60 dakika, 100 dakika veriyoruz
        result = await controller.turn_on("pump_01", duration_minutes=100)

        assert result.success is True
        # Duration should be capped to 60

    @pytest.mark.asyncio
    async def test_turn_off_success(self, controller):
        result = await controller.turn_off("pump_01", reason="test")

        assert result.success is True
        assert result.device_id == "pump_01"
        assert result.command == "off"

    @pytest.mark.asyncio
    async def test_turn_off_unknown_device(self, controller):
        result = await controller.turn_off("unknown_device")

        assert result.success is False
        assert "Unknown device" in result.error

    @pytest.mark.asyncio
    async def test_turn_on_without_mqtt(self, device_config):
        """MQTT olmadan turn_on (simulation mode)"""
        with patch('actions.relay_control.get_state_manager') as mock_sm:
            mock_sm.return_value.read.return_value = {
                "devices": {},
                "pending_actions": []
            }
            mock_sm.return_value.write = Mock()

            controller = RelayController(None, device_config)
            result = await controller.turn_on("pump_01", duration_minutes=10)

            # Should succeed in simulation mode
            assert result.success is True

    @pytest.mark.asyncio
    async def test_scheduled_off(self, controller):
        """Schedule off task'ı test et"""
        await controller.schedule_off("pump_01", after_minutes=1)

        # Task should be created
        assert "pump_01" in controller._scheduled_off_tasks
        assert not controller._scheduled_off_tasks["pump_01"].done()

        # Cancel it
        assert controller._cancel_scheduled_off("pump_01") is True
        assert "pump_01" not in controller._scheduled_off_tasks

    @pytest.mark.asyncio
    async def test_shutdown(self, controller):
        """Shutdown tüm scheduled tasks'ları iptal etmeli"""
        await controller.schedule_off("pump_01", after_minutes=10)
        await controller.schedule_off("fan_01", after_minutes=10)

        await controller.shutdown()

        assert len(controller._scheduled_off_tasks) == 0


# ==================== ActionStatus Tests ====================

class TestActionStatus:
    """ActionStatus enum testleri"""

    def test_values(self):
        assert ActionStatus.PENDING.value == "pending"
        assert ActionStatus.EXECUTING.value == "executing"
        assert ActionStatus.COMPLETED.value == "completed"
        assert ActionStatus.FAILED.value == "failed"
        assert ActionStatus.SKIPPED.value == "skipped"


# ==================== ActionResult Tests ====================

class TestActionResult:
    """ActionResult dataclass testleri"""

    def test_success_result(self):
        result = ActionResult(
            action_id="abc123",
            status=ActionStatus.COMPLETED,
            device_id="pump_01",
            command="pump_on"
        )
        assert result.action_id == "abc123"
        assert result.status == ActionStatus.COMPLETED
        assert result.error is None

    def test_failed_result(self):
        result = ActionResult(
            action_id="abc123",
            status=ActionStatus.FAILED,
            device_id="pump_01",
            error="Command failed"
        )
        assert result.status == ActionStatus.FAILED
        assert result.error == "Command failed"


# ==================== ActionExecutor Tests ====================

class TestActionExecutor:
    """ActionExecutor testleri"""

    @pytest.fixture
    def device_config(self):
        return {
            "relays": {
                "pump_01": {"max_on_duration_minutes": 60},
                "fan_01": {"max_on_duration_minutes": 120}
            }
        }

    @pytest.fixture
    def mock_relay_controller(self):
        controller = Mock(spec=RelayController)
        controller.turn_on = AsyncMock(return_value=RelayCommandResult(
            success=True,
            device_id="pump_01",
            command="on"
        ))
        controller.turn_off = AsyncMock(return_value=RelayCommandResult(
            success=True,
            device_id="pump_01",
            command="off"
        ))
        return controller

    @pytest.fixture
    def executor(self, mock_relay_controller, device_config):
        with patch('actions.executor.get_state_manager') as mock_sm:
            mock_sm.return_value.read.return_value = {
                "devices": {},
                "pending_actions": []
            }
            mock_sm.return_value.write = Mock()
            return ActionExecutor(mock_relay_controller, device_config)

    def test_init(self, executor):
        assert executor.relay_controller is not None
        assert executor.max_retries == 3
        assert executor.stats.total_processed == 0

    @pytest.mark.asyncio
    async def test_process_empty_pending(self, executor):
        """Boş pending actions listesi"""
        results = await executor.process_pending_actions()
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_process_pump_on_action(self, executor, mock_relay_controller):
        """pump_on action'ı işle"""
        with patch('actions.executor.get_state_manager') as mock_sm:
            mock_sm.return_value.read.return_value = {
                "devices": {},
                "pending_actions": [
                    {
                        "id": "test123",
                        "action": "pump_on",
                        "device": "pump_01",
                        "duration_minutes": 10,
                        "reason": "low_soil_moisture",
                        "status": "pending"
                    }
                ]
            }
            mock_sm.return_value.write = Mock()

            executor.state_manager = mock_sm.return_value
            results = await executor.process_pending_actions()

            assert len(results) == 1
            assert results[0].status == ActionStatus.COMPLETED
            mock_relay_controller.turn_on.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_fan_on_action(self, executor, mock_relay_controller):
        """fan_on action'ı işle"""
        with patch('actions.executor.get_state_manager') as mock_sm:
            mock_sm.return_value.read.return_value = {
                "devices": {},
                "pending_actions": [
                    {
                        "id": "test456",
                        "action": "fan_on",
                        "device": "fan_01",
                        "duration_minutes": 30,
                        "reason": "high_temperature",
                        "status": "pending"
                    }
                ]
            }
            mock_sm.return_value.write = Mock()

            executor.state_manager = mock_sm.return_value
            results = await executor.process_pending_actions()

            assert len(results) == 1
            assert results[0].status == ActionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_process_unknown_action(self, executor):
        """Bilinmeyen action tipi"""
        with patch('actions.executor.get_state_manager') as mock_sm:
            mock_sm.return_value.read.return_value = {
                "devices": {},
                "pending_actions": [
                    {
                        "id": "test789",
                        "action": "unknown_action",
                        "device": "pump_01",
                        "status": "pending"
                    }
                ]
            }
            mock_sm.return_value.write = Mock()

            executor.state_manager = mock_sm.return_value
            results = await executor.process_pending_actions()

            assert len(results) == 1
            assert results[0].status == ActionStatus.FAILED
            assert "Unknown action" in results[0].error

    @pytest.mark.asyncio
    async def test_process_none_action(self, executor):
        """'none' action'ı skipped olmalı"""
        with patch('actions.executor.get_state_manager') as mock_sm:
            mock_sm.return_value.read.return_value = {
                "devices": {},
                "pending_actions": [
                    {
                        "id": "test000",
                        "action": "none",
                        "status": "pending"
                    }
                ]
            }
            mock_sm.return_value.write = Mock()

            executor.state_manager = mock_sm.return_value
            results = await executor.process_pending_actions()

            assert len(results) == 1
            assert results[0].status == ActionStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, executor, mock_relay_controller):
        """Başarısız action retry edilmeli"""
        mock_relay_controller.turn_on = AsyncMock(return_value=RelayCommandResult(
            success=False,
            device_id="pump_01",
            command="on",
            error="MQTT error"
        ))

        action = {
            "id": "retry_test",
            "action": "pump_on",
            "device": "pump_01",
            "status": "pending",
            "retry_count": 0
        }

        result = await executor.process_single_action(action)

        # Should remain pending for retry
        assert result.status == ActionStatus.PENDING

    @pytest.mark.asyncio
    async def test_max_retry_exceeded(self, executor, mock_relay_controller):
        """Max retry aşıldığında fail olmalı"""
        mock_relay_controller.turn_on = AsyncMock(return_value=RelayCommandResult(
            success=False,
            device_id="pump_01",
            command="on",
            error="MQTT error"
        ))

        action = {
            "id": "max_retry_test",
            "action": "pump_on",
            "device": "pump_01",
            "status": "pending",
            "retry_count": 3  # Already at max
        }

        result = await executor.process_single_action(action)

        # Should be failed
        assert result.status == ActionStatus.FAILED

    def test_get_stats(self, executor):
        stats = executor.get_stats()

        assert "total_processed" in stats
        assert "successful" in stats
        assert "failed" in stats
        assert "skipped" in stats

    def test_get_pending_count(self, executor):
        count = executor.get_pending_count()
        assert isinstance(count, int)

    @pytest.mark.asyncio
    async def test_check_scheduled_shutoffs(self, executor, mock_relay_controller):
        """Scheduled shutoffs kontrolü"""
        past_time = (datetime.utcnow() - timedelta(minutes=5)).isoformat() + "Z"

        with patch('actions.executor.get_state_manager') as mock_sm:
            mock_sm.return_value.read.return_value = {
                "devices": {
                    "pump_01": {
                        "state": "on",
                        "scheduled_off": past_time
                    }
                },
                "pending_actions": []
            }
            mock_sm.return_value.write = Mock()

            executor.state_manager = mock_sm.return_value
            triggered = await executor.check_scheduled_shutoffs()

            assert "pump_01" in triggered
            mock_relay_controller.turn_off.assert_called()

    @pytest.mark.asyncio
    async def test_reset_daily_counters(self, executor):
        """Günlük sayaçları sıfırla"""
        with patch('actions.executor.get_state_manager') as mock_sm:
            mock_sm.return_value.read.return_value = {
                "devices": {
                    "pump_01": {"total_on_time_today_minutes": 45},
                    "fan_01": {"total_on_time_today_minutes": 30}
                },
                "pending_actions": []
            }
            mock_sm.return_value.write = Mock()

            executor.state_manager = mock_sm.return_value
            await executor.reset_daily_counters()

            # Write should be called
            mock_sm.return_value.write.assert_called()


# ==================== Integration Tests ====================

class TestExecutorIntegration:
    """Executor bileşenlerinin entegrasyon testleri"""

    @pytest.mark.asyncio
    async def test_full_action_cycle(self):
        """Tam bir action döngüsünü test et"""
        device_config = {
            "relays": {
                "pump_01": {"max_on_duration_minutes": 60}
            }
        }

        # Mock MQTT
        mock_mqtt = Mock()
        mock_mqtt.send_relay_command = AsyncMock(return_value=RelayCommandResult(
            success=True,
            device_id="pump_01",
            command="on"
        ))

        with patch('actions.relay_control.get_state_manager') as mock_sm_relay, \
             patch('actions.executor.get_state_manager') as mock_sm_exec:

            # Setup state manager mocks
            state_data = {
                "devices": {
                    "pump_01": {
                        "state": "off",
                        "total_on_time_today_minutes": 0
                    }
                },
                "pending_actions": [
                    {
                        "id": "int_test_001",
                        "action": "pump_on",
                        "device": "pump_01",
                        "duration_minutes": 15,
                        "reason": "irrigation_schedule",
                        "status": "pending"
                    }
                ]
            }

            mock_sm_relay.return_value.read.return_value = state_data.copy()
            mock_sm_relay.return_value.write = Mock()
            mock_sm_exec.return_value.read.return_value = state_data.copy()
            mock_sm_exec.return_value.write = Mock()

            # Create components
            controller = RelayController(mock_mqtt, device_config)
            executor = ActionExecutor(controller, device_config)

            # Process actions
            results = await executor.process_pending_actions()

            assert len(results) == 1
            assert results[0].status == ActionStatus.COMPLETED
            assert results[0].device_id == "pump_01"

            # Verify stats
            stats = executor.get_stats()
            assert stats["successful"] == 1

            # Cleanup
            await controller.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
