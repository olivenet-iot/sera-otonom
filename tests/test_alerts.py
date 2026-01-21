"""
Sera Otonom - Alert Manager Unit Tests

pytest ile alert modülü testleri
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from actions.alert import (
    AlertManager,
    AlertLevel,
    AlertResult,
    get_alert_manager,
    send_alert,
)


# ==================== AlertLevel Tests ====================

class TestAlertLevel:
    """AlertLevel enum testleri"""

    def test_values(self):
        assert AlertLevel.INFO.value == "info"
        assert AlertLevel.WARNING.value == "warning"
        assert AlertLevel.CRITICAL.value == "critical"


# ==================== AlertResult Tests ====================

class TestAlertResult:
    """AlertResult dataclass testleri"""

    def test_success_result(self):
        result = AlertResult(
            success=True,
            level=AlertLevel.CRITICAL,
            message="Test alert"
        )
        assert result.success is True
        assert result.level == AlertLevel.CRITICAL
        assert result.message == "Test alert"
        assert result.error is None
        assert result.rate_limited is False

    def test_error_result(self):
        result = AlertResult(
            success=False,
            level=AlertLevel.WARNING,
            message="Test alert",
            error="Connection failed"
        )
        assert result.success is False
        assert result.error == "Connection failed"

    def test_rate_limited_result(self):
        result = AlertResult(
            success=False,
            level=AlertLevel.INFO,
            message="Test alert",
            rate_limited=True
        )
        assert result.rate_limited is True

    def test_default_timestamp(self):
        result = AlertResult(
            success=True,
            level=AlertLevel.INFO,
            message="Test"
        )
        assert result.timestamp is not None
        assert isinstance(result.timestamp, datetime)


# ==================== AlertManager Init Tests ====================

class TestAlertManagerInit:
    """AlertManager initialization testleri"""

    def test_init_disabled(self):
        """Disabled config ile init"""
        manager = AlertManager({"enabled": False})

        assert manager.enabled is False
        assert manager.telegram_enabled is False

    def test_init_enabled_no_telegram(self):
        """Enabled ama Telegram yok"""
        manager = AlertManager({
            "enabled": True,
            "telegram": {"enabled": False}
        })

        assert manager.enabled is True
        assert manager.telegram_enabled is False

    def test_init_with_telegram(self):
        """Telegram config ile init"""
        manager = AlertManager({
            "enabled": True,
            "telegram": {
                "enabled": True,
                "bot_token": "123:ABC",
                "chat_id": "456"
            },
            "levels": {
                "critical": True,
                "warning": True,
                "info": False
            },
            "rate_limit": {
                "max_per_hour": 5,
                "cooldown_seconds": 60
            }
        })

        assert manager.enabled is True
        assert manager.telegram_enabled is True
        assert manager.bot_token == "123:ABC"
        assert manager.chat_id == "456"
        assert manager.max_per_hour == 5
        assert manager.cooldown_seconds == 60
        assert manager.level_enabled[AlertLevel.CRITICAL] is True
        assert manager.level_enabled[AlertLevel.WARNING] is True
        assert manager.level_enabled[AlertLevel.INFO] is False

    def test_init_telegram_missing_credentials(self):
        """Telegram enabled ama credentials yok"""
        manager = AlertManager({
            "enabled": True,
            "telegram": {
                "enabled": True,
                "bot_token": "",
                "chat_id": ""
            }
        })

        # Should disable telegram due to missing credentials
        assert manager.telegram_enabled is False

    def test_init_default_levels(self):
        """Default level değerleri"""
        manager = AlertManager({"enabled": True})

        assert manager.level_enabled[AlertLevel.CRITICAL] is True
        assert manager.level_enabled[AlertLevel.WARNING] is True
        assert manager.level_enabled[AlertLevel.INFO] is False

    def test_init_default_rate_limit(self):
        """Default rate limit değerleri"""
        manager = AlertManager({"enabled": True})

        assert manager.max_per_hour == 10
        assert manager.cooldown_seconds == 300


# ==================== AlertManager Send Tests ====================

class TestAlertManagerSend:
    """AlertManager send metodu testleri"""

    @pytest.fixture
    def enabled_manager(self):
        return AlertManager({
            "enabled": True,
            "telegram": {"enabled": False},
            "levels": {
                "critical": True,
                "warning": True,
                "info": True
            }
        })

    @pytest.fixture
    def disabled_manager(self):
        return AlertManager({"enabled": False})

    @pytest.mark.asyncio
    async def test_send_disabled(self, disabled_manager):
        """Disabled manager ile send"""
        result = await disabled_manager.send(
            AlertLevel.CRITICAL,
            "Test message"
        )

        assert result.success is True
        assert result.error == "Alerts disabled"

    @pytest.mark.asyncio
    async def test_send_level_disabled(self, enabled_manager):
        """Disabled level ile send"""
        enabled_manager.level_enabled[AlertLevel.INFO] = False

        result = await enabled_manager.send(
            AlertLevel.INFO,
            "Test info message"
        )

        assert result.success is True
        assert "Level info disabled" in result.error

    @pytest.mark.asyncio
    async def test_send_success_no_telegram(self, enabled_manager):
        """Telegram olmadan başarılı send"""
        result = await enabled_manager.send(
            AlertLevel.CRITICAL,
            "Test critical message"
        )

        assert result.success is True
        assert result.level == AlertLevel.CRITICAL
        assert result.message == "Test critical message"

    @pytest.mark.asyncio
    async def test_send_critical_convenience(self, enabled_manager):
        """send_critical convenience metodu"""
        result = await enabled_manager.send_critical("Critical alert")

        assert result.success is True
        assert result.level == AlertLevel.CRITICAL

    @pytest.mark.asyncio
    async def test_send_warning_convenience(self, enabled_manager):
        """send_warning convenience metodu"""
        result = await enabled_manager.send_warning("Warning alert")

        assert result.success is True
        assert result.level == AlertLevel.WARNING

    @pytest.mark.asyncio
    async def test_send_info_convenience(self, enabled_manager):
        """send_info convenience metodu"""
        result = await enabled_manager.send_info("Info alert")

        assert result.success is True
        assert result.level == AlertLevel.INFO


# ==================== Rate Limiting Tests ====================

class TestRateLimiting:
    """Rate limiting testleri"""

    @pytest.fixture
    def rate_limited_manager(self):
        return AlertManager({
            "enabled": True,
            "telegram": {"enabled": False},
            "levels": {"critical": True, "warning": True, "info": True},
            "rate_limit": {
                "max_per_hour": 3,
                "cooldown_seconds": 60
            }
        })

    def test_rate_limit_hourly(self, rate_limited_manager):
        """Hourly rate limit"""
        # Simulate 3 sent alerts
        now = datetime.now()
        rate_limited_manager._sent_alerts = [
            now - timedelta(minutes=1),
            now - timedelta(minutes=2),
            now - timedelta(minutes=3)
        ]

        # Should be rate limited
        assert rate_limited_manager._is_rate_limited() is True

    def test_rate_limit_not_exceeded(self, rate_limited_manager):
        """Rate limit not exceeded"""
        now = datetime.now()
        rate_limited_manager._sent_alerts = [
            now - timedelta(minutes=1),
            now - timedelta(minutes=2)
        ]

        # Should NOT be rate limited (2 < 3)
        assert rate_limited_manager._is_rate_limited() is False

    def test_rate_limit_old_alerts_cleaned(self, rate_limited_manager):
        """Old alerts (>1 hour) cleaned from tracking"""
        now = datetime.now()
        rate_limited_manager._sent_alerts = [
            now - timedelta(hours=2),  # Old, should be cleaned
            now - timedelta(hours=1, minutes=30),  # Old, should be cleaned
            now - timedelta(minutes=30)  # Recent, should remain
        ]

        # Should NOT be rate limited after cleaning old alerts
        assert rate_limited_manager._is_rate_limited() is False
        # Only recent alert should remain
        assert len(rate_limited_manager._sent_alerts) == 1

    def test_cooldown_active(self, rate_limited_manager):
        """Cooldown per alert type"""
        now = datetime.now()
        rate_limited_manager._last_alert_by_type["temp_high"] = now - timedelta(seconds=30)

        # Cooldown is 60s, only 30s passed
        assert rate_limited_manager._is_rate_limited("temp_high") is True

    def test_cooldown_expired(self, rate_limited_manager):
        """Cooldown expired"""
        now = datetime.now()
        rate_limited_manager._last_alert_by_type["temp_high"] = now - timedelta(seconds=120)

        # Cooldown is 60s, 120s passed
        assert rate_limited_manager._is_rate_limited("temp_high") is False

    def test_no_cooldown_different_type(self, rate_limited_manager):
        """Different alert type not affected by cooldown"""
        now = datetime.now()
        rate_limited_manager._last_alert_by_type["temp_high"] = now - timedelta(seconds=30)

        # Different type should not be rate limited
        assert rate_limited_manager._is_rate_limited("humidity_low") is False

    @pytest.mark.asyncio
    async def test_rate_limited_send_returns_flag(self, rate_limited_manager):
        """Rate limited send returns rate_limited flag"""
        # Max out the rate limit
        now = datetime.now()
        rate_limited_manager._sent_alerts = [
            now - timedelta(minutes=1),
            now - timedelta(minutes=2),
            now - timedelta(minutes=3)
        ]

        result = await rate_limited_manager.send(
            AlertLevel.CRITICAL,
            "Test message"
        )

        assert result.success is False
        assert result.rate_limited is True
        assert result.error == "Rate limited"


# ==================== Message Format Tests ====================

class TestMessageFormat:
    """Message formatting testleri"""

    @pytest.fixture
    def manager(self):
        return AlertManager({"enabled": True})

    def test_format_message_critical(self, manager):
        """Critical message format"""
        msg = manager._format_message(
            AlertLevel.CRITICAL,
            "High temperature detected!"
        )

        assert "SERA OTONOM - CRITICAL" in msg
        assert "High temperature detected!" in msg
        # Check emoji (🚨)
        assert "\U0001F6A8" in msg

    def test_format_message_warning(self, manager):
        """Warning message format"""
        msg = manager._format_message(
            AlertLevel.WARNING,
            "Soil moisture low"
        )

        assert "SERA OTONOM - WARNING" in msg
        assert "Soil moisture low" in msg
        # Check emoji (⚠️)
        assert "\u26A0" in msg

    def test_format_message_info(self, manager):
        """Info message format"""
        msg = manager._format_message(
            AlertLevel.INFO,
            "System started"
        )

        assert "SERA OTONOM - INFO" in msg
        assert "System started" in msg
        # Check emoji (ℹ️)
        assert "\u2139" in msg

    def test_format_message_with_details(self, manager):
        """Message with details"""
        msg = manager._format_message(
            AlertLevel.CRITICAL,
            "Sensor alert",
            {"sensor": "temp_01", "value": 45.5, "threshold": 40}
        )

        assert "sensor: temp_01" in msg
        assert "value: 45.5" in msg
        assert "threshold: 40" in msg
        # Bullet point
        assert "\u2022" in msg

    def test_format_message_has_timestamp(self, manager):
        """Message includes timestamp"""
        msg = manager._format_message(
            AlertLevel.INFO,
            "Test"
        )

        # Should have clock emoji and time
        assert "\U0001F550" in msg  # 🕐


# ==================== Telegram Send Tests ====================

class TestTelegramSend:
    """Telegram API send testleri"""

    @pytest.fixture
    def telegram_manager(self):
        return AlertManager({
            "enabled": True,
            "telegram": {
                "enabled": True,
                "bot_token": "123:ABC",
                "chat_id": "456"
            },
            "levels": {"critical": True, "warning": True, "info": True}
        })

    @pytest.mark.asyncio
    async def test_send_telegram_success(self, telegram_manager):
        """Successful Telegram send"""
        mock_response = MagicMock()
        mock_response.status = 200

        mock_session = MagicMock()
        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_session.post.return_value = mock_post_ctx

        with patch.object(telegram_manager, '_get_session', new=AsyncMock(return_value=mock_session)):
            success, error = await telegram_manager._send_telegram("Test message")

            assert success is True
            assert error is None

    @pytest.mark.asyncio
    async def test_send_telegram_api_error(self, telegram_manager):
        """Telegram API error"""
        mock_response = MagicMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Bad Request")

        mock_session = MagicMock()
        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_session.post.return_value = mock_post_ctx

        with patch.object(telegram_manager, '_get_session', new=AsyncMock(return_value=mock_session)):
            success, error = await telegram_manager._send_telegram("Test message")

            assert success is False
            assert "400" in error

    @pytest.mark.asyncio
    async def test_send_telegram_missing_credentials(self, telegram_manager):
        """Missing Telegram credentials"""
        telegram_manager.bot_token = ""
        telegram_manager.chat_id = ""

        success, error = await telegram_manager._send_telegram("Test message")

        assert success is False
        assert "Missing Telegram credentials" in error

    @pytest.mark.asyncio
    async def test_send_with_telegram_integration(self, telegram_manager):
        """Full send with Telegram enabled"""
        mock_response = MagicMock()
        mock_response.status = 200

        mock_session = MagicMock()
        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_session.post.return_value = mock_post_ctx

        with patch.object(telegram_manager, '_get_session', new=AsyncMock(return_value=mock_session)):
            result = await telegram_manager.send(
                AlertLevel.CRITICAL,
                "Test critical alert",
                {"sensor": "temp", "value": 50}
            )

            assert result.success is True
            assert len(telegram_manager._sent_alerts) == 1

    @pytest.mark.asyncio
    async def test_send_with_alert_type_tracking(self, telegram_manager):
        """Alert type tracking for cooldown"""
        mock_response = MagicMock()
        mock_response.status = 200

        mock_session = MagicMock()
        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_session.post.return_value = mock_post_ctx

        with patch.object(telegram_manager, '_get_session', new=AsyncMock(return_value=mock_session)):
            await telegram_manager.send(
                AlertLevel.CRITICAL,
                "High temp",
                alert_type="temp_high"
            )

            assert "temp_high" in telegram_manager._last_alert_by_type


# ==================== Session Management Tests ====================

class TestSessionManagement:
    """aiohttp session yönetimi testleri"""

    @pytest.fixture
    def manager(self):
        return AlertManager({"enabled": True})

    @pytest.mark.asyncio
    async def test_get_session_creates_new(self, manager):
        """Session lazily created"""
        assert manager._session is None

        session = await manager._get_session()

        assert session is not None
        assert manager._session is session

        await manager.close()

    @pytest.mark.asyncio
    async def test_close_session(self, manager):
        """Session properly closed"""
        await manager._get_session()
        assert manager._session is not None

        await manager.close()

        assert manager._session is None


# ==================== Global Functions Tests ====================

class TestGlobalFunctions:
    """Global helper function testleri"""

    def test_get_alert_manager_creates_instance(self):
        """get_alert_manager creates instance"""
        # Reset global
        import actions.alert as alert_module
        alert_module._alert_manager = None

        manager = get_alert_manager({"enabled": False})

        assert manager is not None
        assert manager.enabled is False

        # Cleanup
        alert_module._alert_manager = None

    def test_get_alert_manager_returns_same_instance(self):
        """get_alert_manager returns same instance"""
        import actions.alert as alert_module
        alert_module._alert_manager = None

        manager1 = get_alert_manager({"enabled": True})
        manager2 = get_alert_manager()  # No config needed

        assert manager1 is manager2

        # Cleanup
        alert_module._alert_manager = None

    @pytest.mark.asyncio
    async def test_send_alert_shortcut(self):
        """send_alert shortcut function"""
        import actions.alert as alert_module
        alert_module._alert_manager = None

        result = await send_alert(
            AlertLevel.INFO,
            "Test message"
        )

        assert result is not None
        assert result.level == AlertLevel.INFO

        # Cleanup
        alert_module._alert_manager = None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
