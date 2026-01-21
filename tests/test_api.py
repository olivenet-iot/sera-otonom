"""API endpoint tests"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, AsyncMock, patch

from ui.backend.main import app
from ui.backend import dependencies

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_brain():
    """Mock brain for all tests"""
    mock = Mock()
    mock.is_running = True
    mock._initialized = True
    mock._cycle_count = 5
    mock.get_status.return_value = {
        "is_running": True,
        "initialized": True,
        "cycle_count": 5,
        "use_claude": True,
        "use_fallback": True,
        "dry_run": False,
        "config": {"cycle_interval": 300, "claude_timeout": 120}
    }
    mock.relay_controller = Mock()
    mock.relay_controller.turn_on = AsyncMock(return_value=Mock(
        success=True, device_id="pump_01", command="on",
        message="OK", error=None
    ))
    mock.relay_controller.turn_off = AsyncMock(return_value=Mock(
        success=True, device_id="pump_01", command="off",
        message="OK", error=None
    ))

    with patch.object(dependencies, '_brain_instance', mock):
        yield mock


@pytest.fixture(autouse=True)
def mock_state_manager():
    """Mock state manager for all tests"""
    mock = Mock()
    mock.read.return_value = {
        "mode": {"current": "auto"},
        "devices": {
            "pump_01": {"state": "off", "total_on_time_today_minutes": 0},
            "fan_01": {"state": "off", "total_on_time_today_minutes": 0}
        },
        "decisions": [],
        "thoughts": []
    }
    mock.write = Mock()

    with patch.object(dependencies, '_get_state_manager', return_value=mock):
        yield mock


class TestHealthEndpoints:
    def test_health_check(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data

    def test_info(self):
        response = client.get("/api/info")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "uptime_seconds" in data


class TestBrainEndpoints:
    def test_get_status(self):
        response = client.get("/api/brain/status")
        assert response.status_code == 200
        data = response.json()
        assert "is_running" in data
        assert "mode" in data

    def test_get_decisions(self):
        response = client.get("/api/brain/decisions")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_decisions_pagination(self):
        response = client.get("/api/brain/decisions?limit=5&offset=0")
        assert response.status_code == 200

    def test_get_thoughts(self):
        response = client.get("/api/brain/thoughts")
        assert response.status_code == 200

    def test_ask_brain_placeholder(self):
        response = client.post("/api/brain/ask", json={"question": "Test?"})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "not yet implemented" in data["error"]


class TestControlEndpoints:
    def test_set_mode_auto(self):
        response = client.post("/api/control/mode", json={"mode": "auto"})
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_set_mode_paused(self):
        response = client.post("/api/control/mode", json={"mode": "paused"})
        assert response.status_code == 200

    def test_override_pump_on(self):
        response = client.post("/api/control/override", json={
            "device": "pump_01",
            "action": "on",
            "duration_minutes": 10
        })
        assert response.status_code == 200

    def test_override_invalid_device(self):
        response = client.post("/api/control/override", json={
            "device": "invalid",
            "action": "on"
        })
        assert response.status_code == 422  # Validation error
