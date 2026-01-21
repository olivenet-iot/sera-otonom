"""
Sera Otonom - Brain Unit Tests

pytest ile brain modülü testleri
"""

import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

# Test edilecek modüller
from core.claude_runner import ClaudeRunner, ClaudeResponse, FallbackDecisionMaker
from core.scheduler import SeraScheduler, ScheduledTask, TaskStatus, TaskStats
from core.brain import SeraBrain


# ==================== ClaudeRunner Tests ====================

class TestClaudeResponse:
    """ClaudeResponse dataclass testleri"""

    def test_success_response(self):
        response = ClaudeResponse(
            success=True,
            raw_output="test output",
            analysis={"summary": "test"},
            decision={"action": "none"},
            reasoning="test reasoning"
        )
        assert response.success is True
        assert response.error is None

    def test_error_response(self):
        response = ClaudeResponse(
            success=False,
            error="Test error"
        )
        assert response.success is False
        assert response.error == "Test error"

    def test_default_timestamp(self):
        response = ClaudeResponse(success=True)
        assert response.timestamp is not None


class TestClaudeRunner:
    """ClaudeRunner testleri"""

    def test_init(self):
        runner = ClaudeRunner(timeout=60, max_retries=2)
        assert runner.timeout == 60
        assert runner.max_retries == 2

    def test_build_prompt(self):
        runner = ClaudeRunner()
        context = {
            "sensors": {"temperature": {"value": 25}},
            "weather": {"current": {"temp": 20}}
        }

        with patch.object(runner, '_load_system_prompt', return_value="Test system prompt"):
            prompt = runner.build_prompt(context)

        assert "Test system prompt" in prompt
        assert "temperature" in prompt
        assert "25" in prompt

    def test_parse_response_valid_json(self):
        runner = ClaudeRunner()

        raw_output = """
        Some text before
        ```json
        {
            "analysis": {"summary": "Test summary"},
            "decision": {"action": "none", "confidence": 0.8}
        }
        ```
        Some text after
        """

        response = runner.parse_response(raw_output)
        assert response.success is True
        assert response.decision["action"] == "none"
        assert response.analysis["summary"] == "Test summary"

    def test_parse_response_no_json(self):
        runner = ClaudeRunner()
        raw_output = "No JSON here"

        response = runner.parse_response(raw_output)
        assert response.success is False
        assert "No JSON block" in response.error

    def test_parse_response_invalid_json(self):
        runner = ClaudeRunner()
        raw_output = "```json\n{invalid json}\n```"

        response = runner.parse_response(raw_output)
        assert response.success is False
        assert "JSON parse error" in response.error

    def test_parse_response_missing_decision(self):
        runner = ClaudeRunner()
        raw_output = '```json\n{"analysis": {}}\n```'

        response = runner.parse_response(raw_output)
        assert response.success is False
        assert "No 'decision' field" in response.error

    def test_build_reasoning(self):
        runner = ClaudeRunner()
        analysis = {
            "summary": "Test summary",
            "concerns": ["High temp"],
            "positive": ["Good humidity"]
        }
        decision = {
            "action": "fan_on",
            "reason": "Cooling needed",
            "confidence": 0.85
        }

        reasoning = runner._build_reasoning(analysis, decision)

        assert "Test summary" in reasoning
        assert "High temp" in reasoning
        assert "fan_on" in reasoning
        assert "85" in reasoning  # %85


class TestFallbackDecisionMaker:
    """FallbackDecisionMaker testleri"""

    @pytest.fixture
    def fallback(self):
        thresholds = {
            "temperature": {
                "optimal_range": [20, 28],
                "warning_low": 15,
                "warning_high": 32,
                "critical_low": 10,
                "critical_high": 38
            },
            "humidity": {
                "optimal_range": [60, 80],
                "warning_high": 90
            },
            "soil_moisture": {
                "optimal_range": [40, 70],
                "warning_low": 30,
                "critical_low": 20,
                "warning_high": 80
            }
        }
        return FallbackDecisionMaker(thresholds)

    def test_normal_conditions(self, fallback):
        sensor_data = {
            "temperature": {"value": 25},
            "humidity": {"value": 70},
            "soil_moisture": {"value": 50}
        }

        result = fallback.make_decision(sensor_data)

        assert result.success is True
        assert result.decision["action"] == "none"
        assert "normal" in result.decision["reason"].lower()

    def test_high_temperature(self, fallback):
        sensor_data = {
            "temperature": {"value": 40},
            "humidity": {"value": 70},
            "soil_moisture": {"value": 50}
        }

        result = fallback.make_decision(sensor_data)

        assert result.success is True
        assert result.decision["action"] == "fan_on"
        assert result.decision["device"] == "fan_01"

    def test_low_soil_moisture(self, fallback):
        sensor_data = {
            "temperature": {"value": 25},
            "humidity": {"value": 70},
            "soil_moisture": {"value": 15}  # Kritik düşük
        }

        result = fallback.make_decision(sensor_data)

        assert result.success is True
        assert result.decision["action"] == "pump_on"
        assert result.decision["device"] == "pump_01"
        assert result.decision["duration_minutes"] == 15

    def test_high_humidity(self, fallback):
        sensor_data = {
            "temperature": {"value": 25},
            "humidity": {"value": 95},  # Yüksek
            "soil_moisture": {"value": 50}
        }

        result = fallback.make_decision(sensor_data)

        assert result.success is True
        assert result.decision["action"] == "fan_on"


# ==================== Scheduler Tests ====================

class TestScheduledTask:
    """ScheduledTask dataclass testleri"""

    def test_default_values(self):
        def dummy():
            pass

        task = ScheduledTask(
            name="test",
            callback=dummy,
            interval_seconds=60
        )

        assert task.enabled is True
        assert task.status == TaskStatus.PENDING
        assert task.stats.run_count == 0


class TestSeraScheduler:
    """SeraScheduler testleri"""

    @pytest.fixture
    def scheduler(self):
        return SeraScheduler(default_interval_seconds=5)

    def test_init(self, scheduler):
        assert scheduler.default_interval == 5
        assert scheduler.is_running is False
        assert len(scheduler.tasks) == 0

    def test_add_task(self, scheduler):
        def dummy():
            pass

        result = scheduler.add_task("test", dummy, interval_seconds=10)

        assert result is True
        assert "test" in scheduler.tasks
        assert scheduler.tasks["test"].interval_seconds == 10

    def test_add_duplicate_task(self, scheduler):
        def dummy():
            pass

        scheduler.add_task("test", dummy)
        result = scheduler.add_task("test", dummy)

        assert result is False

    def test_remove_task(self, scheduler):
        def dummy():
            pass

        scheduler.add_task("test", dummy)
        result = scheduler.remove_task("test")

        assert result is True
        assert "test" not in scheduler.tasks

    def test_remove_nonexistent_task(self, scheduler):
        result = scheduler.remove_task("nonexistent")
        assert result is False

    def test_enable_disable_task(self, scheduler):
        def dummy():
            pass

        scheduler.add_task("test", dummy, enabled=True)

        scheduler.disable_task("test")
        assert scheduler.tasks["test"].enabled is False

        scheduler.enable_task("test")
        assert scheduler.tasks["test"].enabled is True

    def test_get_task_info(self, scheduler):
        def dummy():
            pass

        scheduler.add_task("test", dummy, interval_seconds=30)
        info = scheduler.get_task_info("test")

        assert info["name"] == "test"
        assert info["interval_seconds"] == 30
        assert info["enabled"] is True
        assert info["stats"]["run_count"] == 0

    @pytest.mark.asyncio
    async def test_execute_sync_task(self, scheduler):
        results = []

        def sync_callback():
            results.append("executed")
            return "result"

        scheduler.add_task("test", sync_callback)
        result = await scheduler.run_task_once("test")

        assert result == "result"
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_execute_async_task(self, scheduler):
        results = []

        async def async_callback():
            results.append("executed")
            return "async result"

        scheduler.add_task("test", async_callback)
        result = await scheduler.run_task_once("test")

        assert result == "async result"
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_task_failure(self, scheduler):
        def failing_callback():
            raise ValueError("Test error")

        scheduler.add_task("test", failing_callback)
        result = await scheduler.run_task_once("test")

        assert result is None
        assert scheduler.tasks["test"].stats.failure_count == 1
        assert "Test error" in scheduler.tasks["test"].stats.last_error

    @pytest.mark.asyncio
    async def test_start_stop(self, scheduler):
        call_count = [0]

        async def counter():
            call_count[0] += 1

        scheduler.add_task("counter", counter, interval_seconds=1, run_immediately=True)

        await scheduler.start()
        assert scheduler.is_running is True

        await asyncio.sleep(0.2)

        await scheduler.stop()
        assert scheduler.is_running is False

        # Run immediately ile en az 1 kez çalışmış olmalı
        assert call_count[0] >= 1


# ==================== SeraBrain Tests ====================

class TestSeraBrain:
    """SeraBrain testleri"""

    @pytest.fixture
    def brain(self):
        """Claude ve fallback devre dışı brain"""
        return SeraBrain(use_claude=False, use_fallback=True)

    def test_init(self, brain):
        assert brain.is_running is False
        assert brain._initialized is False
        assert brain.use_fallback is True

    def test_get_status_before_init(self, brain):
        status = brain.get_status()

        assert status["is_running"] is False
        assert status["initialized"] is False
        assert status["cycle_count"] == 0

    @pytest.mark.asyncio
    async def test_initialize(self, brain):
        with patch.object(brain, 'data_collector', None):
            brain.data_collector = Mock()
            brain.data_collector.initialize_connectors = AsyncMock(return_value=True)

            await brain.initialize()

            assert brain._initialized is True
            assert brain.scheduler is not None

    @pytest.mark.asyncio
    async def test_start_stop(self, brain):
        brain._initialized = True
        brain.scheduler = Mock()
        brain.scheduler.start = AsyncMock()
        brain.scheduler.stop = AsyncMock()
        brain.data_collector = Mock()
        brain.data_collector.shutdown = AsyncMock()

        await brain.start()
        assert brain.is_running is True

        await brain.stop()
        assert brain.is_running is False

    @pytest.mark.asyncio
    async def test_make_decision_fallback(self, brain):
        brain.fallback_maker = FallbackDecisionMaker({
            "temperature": {"warning_high": 32, "critical_high": 38}
        })

        context = {
            "sensors": {
                "temperature": {"value": 35}
            }
        }

        result = await brain._make_decision(context)

        assert result.success is True
        assert result.decision["action"] == "fan_on"

    @pytest.mark.asyncio
    async def test_run_cycle_no_collector(self, brain):
        brain._initialized = True
        brain.data_collector = None

        result = await brain.run_cycle()

        assert result["success"] is False
        assert "not initialized" in result["error"].lower()


# ==================== Integration-like Tests ====================

class TestBrainIntegration:
    """Brain bileşenlerinin birlikte çalışma testleri"""

    @pytest.mark.asyncio
    async def test_full_cycle_with_mocks(self):
        """Tam bir brain döngüsünü mock'larla test et"""
        brain = SeraBrain(use_claude=False, use_fallback=True)

        # Mock data collector BEFORE initialize
        mock_collector = Mock()
        mock_collector.collect_context = AsyncMock(return_value={
            "timestamp": datetime.utcnow().isoformat(),
            "sensors": {
                "temperature": {"value": 35, "status": "warning"},
                "humidity": {"value": 70, "status": "normal"},
                "soil_moisture": {"value": 50, "status": "normal"}
            },
            "trends": {},
            "weather": {}
        })
        mock_collector.initialize_connectors = AsyncMock(return_value=True)
        mock_collector.shutdown = AsyncMock()
        mock_collector.get_mqtt_status = Mock(return_value={"connected": False})
        mock_collector.get_weather_status = Mock(return_value={"available": False})

        # Mock state manager
        mock_state = Mock()
        mock_state.read = Mock(return_value={
            "pending_actions": [],
            "decisions": [],
            "stats": {"total_decisions": 0}
        })
        mock_state.update = Mock()
        mock_state.append_to_list = Mock()

        # Patch DataCollector creation
        with patch('core.brain.DataCollector', return_value=mock_collector):
            brain.state_manager = mock_state

            # Initialize
            await brain.initialize()

            # Verify data_collector was set
            assert brain.data_collector is not None

            # Run cycle
            result = await brain.run_cycle()

            # Assertions
            assert result["success"] is True
            assert result["decision"]["action"] == "fan_on"  # Yüksek sıcaklık nedeniyle
            assert "FALLBACK" in result["reasoning"]

            # Cleanup
            await brain.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
