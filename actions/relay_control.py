"""
Sera Otonom - Relay Control

Relay cihazları kontrol eden modül
"""

import logging
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from utils.state_manager import get_state_manager

logger = logging.getLogger(__name__)


@dataclass
class RelayCommandResult:
    """Relay komut sonucu"""
    success: bool
    device_id: str
    command: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    error: Optional[str] = None
    message: Optional[str] = None


class RelayController:
    """Relay kontrolcü"""

    def __init__(self, mqtt_connector, device_config: dict, dry_run: bool = False):
        """
        Controller'ı başlat

        Args:
            mqtt_connector: TTS MQTT connector instance (send_relay_command metoduna sahip)
            device_config: Relay config (devices.yaml içeriği)
            dry_run: Komut göndermeden simüle et
        """
        self.mqtt = mqtt_connector
        self.device_config = device_config
        self.dry_run = dry_run
        self.state_manager = get_state_manager()

        # Scheduled off tasks: device_id -> asyncio.Task
        self._scheduled_off_tasks: Dict[str, asyncio.Task] = {}

        # Safety defaults
        self._default_max_duration = 60  # minutes

        if self.dry_run:
            logger.info("RelayController initialized [DRY-RUN MODE]")
        else:
            logger.info("RelayController initialized")

    async def turn_on(
        self,
        device_id: str,
        duration_minutes: Optional[int] = None,
        reason: Optional[str] = None
    ) -> RelayCommandResult:
        """
        Relay'i aç

        Args:
            device_id: Cihaz ID (örn: "pump_01", "fan_01")
            duration_minutes: Açık kalma süresi (dakika)
            reason: Açma nedeni

        Returns:
            RelayCommandResult
        """
        timestamp = datetime.utcnow()

        # Check device config
        relay_config = self.device_config.get('relays', {}).get(device_id)
        if not relay_config:
            return RelayCommandResult(
                success=False,
                device_id=device_id,
                command="on",
                error=f"Unknown device: {device_id}"
            )

        # Check safety limit
        max_duration = relay_config.get('max_on_duration_minutes', self._default_max_duration)
        if duration_minutes and duration_minutes > max_duration:
            logger.warning(f"Duration {duration_minutes}m exceeds max {max_duration}m for {device_id}")
            duration_minutes = max_duration

        # Cancel any existing scheduled off for this device
        self._cancel_scheduled_off(device_id)

        # Dry-run mode: simulate without sending command
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would turn ON {device_id} (duration: {duration_minutes}m, reason: {reason})")
            return RelayCommandResult(
                success=True,
                device_id=device_id,
                command="on",
                message=f"[DRY-RUN] Device {device_id} would be turned on" + (f" for {duration_minutes} minutes" if duration_minutes else "")
            )

        # Send command via MQTT
        if self.mqtt:
            try:
                result = await self.mqtt.send_relay_command(
                    device_id=device_id,
                    command="on",
                    device_config=self.device_config
                )

                if not result.success:
                    return RelayCommandResult(
                        success=False,
                        device_id=device_id,
                        command="on",
                        error=result.error or "MQTT command failed"
                    )

            except Exception as e:
                logger.error(f"MQTT send failed for {device_id}: {e}")
                return RelayCommandResult(
                    success=False,
                    device_id=device_id,
                    command="on",
                    error=str(e)
                )
        else:
            logger.warning(f"No MQTT connector, simulating turn_on for {device_id}")

        # Update device state
        scheduled_off_time = None
        if duration_minutes:
            scheduled_off_time = (timestamp + timedelta(minutes=duration_minutes)).isoformat() + "Z"
            # Schedule automatic off
            await self.schedule_off(device_id, duration_minutes)

        self._update_device_state(
            device_id=device_id,
            state="on",
            timestamp=timestamp,
            scheduled_off=scheduled_off_time,
            reason=reason
        )

        logger.info(f"Relay {device_id} turned ON (duration: {duration_minutes}m, reason: {reason})")

        return RelayCommandResult(
            success=True,
            device_id=device_id,
            command="on",
            message=f"Device {device_id} turned on" + (f" for {duration_minutes} minutes" if duration_minutes else "")
        )

    async def turn_off(
        self,
        device_id: str,
        reason: Optional[str] = None
    ) -> RelayCommandResult:
        """
        Relay'i kapat

        Args:
            device_id: Cihaz ID
            reason: Kapatma nedeni

        Returns:
            RelayCommandResult
        """
        timestamp = datetime.utcnow()

        # Check device config
        relay_config = self.device_config.get('relays', {}).get(device_id)
        if not relay_config:
            return RelayCommandResult(
                success=False,
                device_id=device_id,
                command="off",
                error=f"Unknown device: {device_id}"
            )

        # Cancel any scheduled off
        self._cancel_scheduled_off(device_id)

        # Get current state to calculate on duration
        device_state = self._get_device_state(device_id)
        on_duration_minutes = None

        if device_state and device_state.get('state') == 'on' and device_state.get('last_changed'):
            try:
                last_changed = datetime.fromisoformat(device_state['last_changed'].replace('Z', '+00:00'))
                on_duration_minutes = (timestamp.replace(tzinfo=last_changed.tzinfo) - last_changed).total_seconds() / 60
            except (ValueError, TypeError):
                pass

        # Dry-run mode: simulate without sending command
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would turn OFF {device_id} (was on for {on_duration_minutes:.1f}m, reason: {reason})" if on_duration_minutes else f"[DRY-RUN] Would turn OFF {device_id} (reason: {reason})")
            return RelayCommandResult(
                success=True,
                device_id=device_id,
                command="off",
                message=f"[DRY-RUN] Device {device_id} would be turned off"
            )

        # Send command via MQTT
        if self.mqtt:
            try:
                result = await self.mqtt.send_relay_command(
                    device_id=device_id,
                    command="off",
                    device_config=self.device_config
                )

                if not result.success:
                    return RelayCommandResult(
                        success=False,
                        device_id=device_id,
                        command="off",
                        error=result.error or "MQTT command failed"
                    )

            except Exception as e:
                logger.error(f"MQTT send failed for {device_id}: {e}")
                return RelayCommandResult(
                    success=False,
                    device_id=device_id,
                    command="off",
                    error=str(e)
                )
        else:
            logger.warning(f"No MQTT connector, simulating turn_off for {device_id}")

        # Update device state
        self._update_device_state(
            device_id=device_id,
            state="off",
            timestamp=timestamp,
            scheduled_off=None,
            last_on_duration=on_duration_minutes,
            reason=reason
        )

        logger.info(f"Relay {device_id} turned OFF (was on for {on_duration_minutes:.1f}m, reason: {reason})" if on_duration_minutes else f"Relay {device_id} turned OFF (reason: {reason})")

        return RelayCommandResult(
            success=True,
            device_id=device_id,
            command="off",
            message=f"Device {device_id} turned off"
        )

    async def schedule_off(self, device_id: str, after_minutes: int) -> None:
        """
        Belirli süre sonra kapatmayı zamanla

        Args:
            device_id: Cihaz ID
            after_minutes: Kaç dakika sonra kapatılacak
        """
        # Cancel existing task if any
        self._cancel_scheduled_off(device_id)

        async def _delayed_off():
            try:
                await asyncio.sleep(after_minutes * 60)
                logger.info(f"Scheduled off triggered for {device_id}")
                await self.turn_off(device_id, reason="scheduled_auto_off")
            except asyncio.CancelledError:
                logger.debug(f"Scheduled off cancelled for {device_id}")
            except Exception as e:
                logger.error(f"Scheduled off failed for {device_id}: {e}")

        task = asyncio.create_task(_delayed_off())
        self._scheduled_off_tasks[device_id] = task
        logger.debug(f"Scheduled off in {after_minutes}m for {device_id}")

    def _cancel_scheduled_off(self, device_id: str) -> bool:
        """
        Zamanlanmış kapatmayı iptal et

        Args:
            device_id: Cihaz ID

        Returns:
            İptal edildiyse True
        """
        task = self._scheduled_off_tasks.pop(device_id, None)
        if task and not task.done():
            task.cancel()
            logger.debug(f"Cancelled scheduled off for {device_id}")
            return True
        return False

    def _get_device_state(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Cihaz durumunu oku"""
        try:
            state = self.state_manager.read("device_states")
            return state.get('devices', {}).get(device_id)
        except Exception as e:
            logger.error(f"Failed to read device state: {e}")
            return None

    def _update_device_state(
        self,
        device_id: str,
        state: str,
        timestamp: datetime,
        scheduled_off: Optional[str] = None,
        last_on_duration: Optional[float] = None,
        reason: Optional[str] = None
    ) -> None:
        """
        Cihaz durumunu güncelle

        Args:
            device_id: Cihaz ID
            state: Yeni durum ("on" veya "off")
            timestamp: Değişim zamanı
            scheduled_off: Planlanan kapanma zamanı (ISO)
            last_on_duration: Son açık kalma süresi (dakika)
            reason: Değişim nedeni
        """
        try:
            device_states = self.state_manager.read("device_states")

            if 'devices' not in device_states:
                device_states['devices'] = {}

            if device_id not in device_states['devices']:
                device_states['devices'][device_id] = {
                    "state": "off",
                    "last_changed": None,
                    "current_operation": None,
                    "scheduled_off": None,
                    "total_on_time_today_minutes": 0,
                    "last_on_duration_minutes": None,
                    "error": None
                }

            device = device_states['devices'][device_id]
            device['state'] = state
            device['last_changed'] = timestamp.isoformat() + "Z"
            device['current_operation'] = reason
            device['scheduled_off'] = scheduled_off
            device['error'] = None

            if last_on_duration is not None:
                device['last_on_duration_minutes'] = round(last_on_duration, 2)
                device['total_on_time_today_minutes'] = round(
                    device.get('total_on_time_today_minutes', 0) + last_on_duration,
                    2
                )

            # Update last_downlink
            device_states['last_downlink'] = {
                "device_id": device_id,
                "command": state,
                "timestamp": timestamp.isoformat() + "Z"
            }

            self.state_manager.write("device_states", device_states)
            logger.debug(f"Device state updated: {device_id} -> {state}")

        except Exception as e:
            logger.error(f"Failed to update device state: {e}")

    def get_device_status(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Cihaz durumunu al"""
        return self._get_device_state(device_id)

    def get_all_device_status(self) -> Dict[str, Any]:
        """Tüm cihaz durumlarını al"""
        try:
            state = self.state_manager.read("device_states")
            return state.get('devices', {})
        except Exception as e:
            logger.error(f"Failed to read device states: {e}")
            return {}

    async def shutdown(self) -> None:
        """Controller'ı kapat, zamanlanmış görevleri iptal et"""
        logger.info("Shutting down RelayController")

        # Cancel all scheduled tasks
        for device_id in list(self._scheduled_off_tasks.keys()):
            self._cancel_scheduled_off(device_id)

        logger.info("RelayController shutdown complete")


if __name__ == "__main__":
    import asyncio

    async def test():
        print("RelayController Test")
        print("=" * 50)

        # Create controller without MQTT
        controller = RelayController(None, {
            "relays": {
                "pump_01": {
                    "max_on_duration_minutes": 60
                },
                "fan_01": {
                    "max_on_duration_minutes": 120
                }
            }
        })

        # Test turn_on (will fail due to unknown device since config is minimal)
        print("\nTest turn_on pump_01:")
        result = await controller.turn_on("pump_01", duration_minutes=10, reason="test")
        print(f"  Result: success={result.success}, message={result.message}")

        # Test turn_off
        print("\nTest turn_off pump_01:")
        result = await controller.turn_off("pump_01", reason="test_off")
        print(f"  Result: success={result.success}, message={result.message}")

        # Shutdown
        await controller.shutdown()
        print("\nController shutdown complete")

    asyncio.run(test())
