"""
Sera Otonom - Alert Manager

Telegram bot notifications for critical greenhouse alerts with rate limiting,
level filtering, and async HTTP communication.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AlertResult:
    """Result of an alert send attempt"""
    success: bool
    level: AlertLevel
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None
    rate_limited: bool = False


class AlertManager:
    """
    Alert manager with Telegram integration.

    Features:
    - Async Telegram notifications
    - Rate limiting (hourly max + cooldown per alert type)
    - Level filtering (critical/warning/info)
    - Graceful fallback when disabled
    """

    TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

    LEVEL_EMOJI = {
        AlertLevel.CRITICAL: "\U0001F6A8",  # 🚨
        AlertLevel.WARNING: "\u26A0\uFE0F",  # ⚠️
        AlertLevel.INFO: "\u2139\uFE0F",     # ℹ️
    }

    def __init__(self, config: dict):
        """
        Initialize alert manager.

        Args:
            config: Alert configuration from settings.yaml
        """
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None

        # Rate limiting tracking
        self._sent_alerts: list[datetime] = []
        self._last_alert_by_type: dict[str, datetime] = {}

        # Parse configuration
        self.enabled = config.get("enabled", False)

        # Telegram settings
        telegram_config = config.get("telegram", {})
        self.telegram_enabled = telegram_config.get("enabled", False) and self.enabled
        self.bot_token = telegram_config.get("bot_token", "")
        self.chat_id = telegram_config.get("chat_id", "")

        # Level settings
        levels_config = config.get("levels", {})
        self.level_enabled = {
            AlertLevel.CRITICAL: levels_config.get("critical", True),
            AlertLevel.WARNING: levels_config.get("warning", True),
            AlertLevel.INFO: levels_config.get("info", False),
        }

        # Rate limit settings
        rate_config = config.get("rate_limit", {})
        self.max_per_hour = rate_config.get("max_per_hour", 10)
        self.cooldown_seconds = rate_config.get("cooldown_seconds", 300)

        # Validate Telegram credentials
        if self.telegram_enabled and (not self.bot_token or not self.chat_id):
            logger.warning("Telegram enabled but credentials missing, disabling")
            self.telegram_enabled = False

        logger.info(
            f"AlertManager initialized: enabled={self.enabled}, "
            f"telegram={self.telegram_enabled}"
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session (lazy initialization)."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self._session

    def _is_rate_limited(self, alert_type: Optional[str] = None) -> bool:
        """
        Check if alert is rate limited.

        Args:
            alert_type: Optional alert type for cooldown check

        Returns:
            True if rate limited, False otherwise
        """
        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)

        # Clean old alerts from tracking list
        self._sent_alerts = [
            ts for ts in self._sent_alerts if ts > one_hour_ago
        ]

        # Check hourly limit
        if len(self._sent_alerts) >= self.max_per_hour:
            logger.warning(f"Rate limit reached: {len(self._sent_alerts)}/{self.max_per_hour} per hour")
            return True

        # Check cooldown for specific alert type
        if alert_type and alert_type in self._last_alert_by_type:
            last_sent = self._last_alert_by_type[alert_type]
            cooldown_end = last_sent + timedelta(seconds=self.cooldown_seconds)
            if now < cooldown_end:
                remaining = (cooldown_end - now).seconds
                logger.debug(f"Cooldown active for '{alert_type}': {remaining}s remaining")
                return True

        return False

    def _format_message(
        self,
        level: AlertLevel,
        message: str,
        details: Optional[dict] = None
    ) -> str:
        """
        Format alert message with emoji and markdown.

        Args:
            level: Alert severity level
            message: Main alert message
            details: Optional key-value details

        Returns:
            Formatted message string
        """
        emoji = self.LEVEL_EMOJI.get(level, "")
        level_name = level.value.upper()

        lines = [
            f"{emoji} *SERA OTONOM - {level_name}*",
            "",
            message,
        ]

        if details:
            lines.append("")
            for key, value in details.items():
                lines.append(f"\u2022 {key}: {value}")

        lines.append("")
        lines.append(f"\U0001F550 {datetime.now().strftime('%H:%M:%S')}")

        return "\n".join(lines)

    async def send(
        self,
        level: AlertLevel,
        message: str,
        details: Optional[dict] = None,
        alert_type: Optional[str] = None
    ) -> AlertResult:
        """
        Send an alert notification.

        Args:
            level: Alert severity level
            message: Alert message
            details: Optional additional details
            alert_type: Optional type for cooldown tracking

        Returns:
            AlertResult with send status
        """
        # Check if alerts are enabled
        if not self.enabled:
            logger.debug("Alerts disabled, skipping send")
            return AlertResult(
                success=True,
                level=level,
                message=message,
                error="Alerts disabled"
            )

        # Check if level is enabled
        if not self.level_enabled.get(level, False):
            logger.debug(f"Alert level {level.value} disabled, skipping")
            return AlertResult(
                success=True,
                level=level,
                message=message,
                error=f"Level {level.value} disabled"
            )

        # Check rate limiting
        if self._is_rate_limited(alert_type):
            logger.warning(f"Alert rate limited: {message[:50]}...")
            return AlertResult(
                success=False,
                level=level,
                message=message,
                error="Rate limited",
                rate_limited=True
            )

        # Log the alert
        logger.info(f"[{level.value.upper()}] {message}")

        # Send via Telegram if enabled
        if self.telegram_enabled:
            formatted = self._format_message(level, message, details)
            success, error = await self._send_telegram(formatted)

            if success:
                # Track successful send for rate limiting
                self._sent_alerts.append(datetime.now())
                if alert_type:
                    self._last_alert_by_type[alert_type] = datetime.now()

                return AlertResult(
                    success=True,
                    level=level,
                    message=message
                )
            else:
                return AlertResult(
                    success=False,
                    level=level,
                    message=message,
                    error=error
                )

        # No Telegram, just logged
        return AlertResult(
            success=True,
            level=level,
            message=message
        )

    async def _send_telegram(self, text: str) -> tuple[bool, Optional[str]]:
        """
        Send message via Telegram API.

        Args:
            text: Message text (supports Markdown)

        Returns:
            Tuple of (success, error_message)
        """
        if not self.bot_token or not self.chat_id:
            return False, "Missing Telegram credentials"

        url = self.TELEGRAM_API_URL.format(token=self.bot_token)
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }

        try:
            session = await self._get_session()
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    logger.debug("Telegram message sent successfully")
                    return True, None
                else:
                    error_text = await response.text()
                    logger.error(f"Telegram API error {response.status}: {error_text}")
                    return False, f"HTTP {response.status}: {error_text}"
        except aiohttp.ClientError as e:
            logger.error(f"Telegram request failed: {e}")
            return False, str(e)
        except Exception as e:
            logger.error(f"Unexpected error sending Telegram: {e}")
            return False, str(e)

    async def send_critical(
        self,
        message: str,
        details: Optional[dict] = None,
        alert_type: Optional[str] = None
    ) -> AlertResult:
        """Send a critical level alert."""
        return await self.send(AlertLevel.CRITICAL, message, details, alert_type)

    async def send_warning(
        self,
        message: str,
        details: Optional[dict] = None,
        alert_type: Optional[str] = None
    ) -> AlertResult:
        """Send a warning level alert."""
        return await self.send(AlertLevel.WARNING, message, details, alert_type)

    async def send_info(
        self,
        message: str,
        details: Optional[dict] = None,
        alert_type: Optional[str] = None
    ) -> AlertResult:
        """Send an info level alert."""
        return await self.send(AlertLevel.INFO, message, details, alert_type)

    async def close(self) -> None:
        """Close aiohttp session and cleanup resources."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            logger.debug("AlertManager session closed")


# Global instance management
_alert_manager: Optional[AlertManager] = None


def get_alert_manager(config: Optional[dict] = None) -> AlertManager:
    """
    Get or create global AlertManager instance.

    Args:
        config: Alert configuration (required on first call)

    Returns:
        AlertManager instance
    """
    global _alert_manager

    if _alert_manager is None:
        if config is None:
            config = {"enabled": False}
        _alert_manager = AlertManager(config)

    return _alert_manager


async def send_alert(
    level: AlertLevel,
    message: str,
    details: Optional[dict] = None,
    alert_type: Optional[str] = None
) -> AlertResult:
    """
    Convenience function to send alert via global manager.

    Args:
        level: Alert severity level
        message: Alert message
        details: Optional additional details
        alert_type: Optional type for cooldown tracking

    Returns:
        AlertResult with send status
    """
    manager = get_alert_manager()
    return await manager.send(level, message, details, alert_type)


if __name__ == "__main__":
    import asyncio

    async def test():
        manager = AlertManager({
            "enabled": True,
            "telegram": {"enabled": False},
            "levels": {"critical": True, "warning": True, "info": True}
        })

        result = await manager.send_critical(
            "Test critical alert",
            {"sensor": "temp", "value": 45.5}
        )
        print(f"Result: {result}")

        await manager.close()

    asyncio.run(test())
