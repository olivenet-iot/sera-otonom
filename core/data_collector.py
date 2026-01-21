"""
Sera Otonom - Data Collector

Tüm veri kaynaklarını toplayan modül
"""

import logging
import asyncio
from typing import Optional, Callable, Any
from datetime import datetime
from pathlib import Path

from connectors import TTSMQTTConnector, WeatherConnector
from processors import SensorProcessor, TrendAnalyzer
from utils.state_manager import get_state_manager
from utils.config_loader import get_config_loader

logger = logging.getLogger(__name__)


class DataCollector:
    """Sensör ve hava verisi toplayan modül"""

    def __init__(
        self,
        settings_config: Optional[dict] = None,
        device_config: Optional[dict] = None,
        threshold_config: Optional[dict] = None
    ):
        """
        Data collector'ı başlat

        Args:
            settings_config: settings.yaml içeriği (None ise otomatik yükler)
            device_config: devices.yaml içeriği (None ise otomatik yükler)
            threshold_config: thresholds.yaml içeriği (None ise otomatik yükler)
        """
        self.config_loader = get_config_loader()
        self.state_manager = get_state_manager()

        # Load configs
        self.settings = settings_config or self.config_loader.load("settings")
        self.device_config = device_config or self._load_device_config()
        self.threshold_config = threshold_config or self.config_loader.load("thresholds")

        # Connectors (lazily initialized)
        self.mqtt_connector: Optional[TTSMQTTConnector] = None
        self.weather_connector: Optional[WeatherConnector] = None

        # Processors
        self.sensor_processor = SensorProcessor(self.device_config, self.threshold_config)
        self.trend_analyzer = TrendAnalyzer(window_hours=6, min_samples=3)

        # Callbacks
        self._sensor_callbacks: list[Callable] = []

        # State
        self._last_weather_update: Optional[datetime] = None
        self._initialized = False

        logger.info("DataCollector initialized")

    def _load_device_config(self) -> dict:
        """Device config yükle (varsa)"""
        try:
            return self.config_loader.load("devices")
        except FileNotFoundError:
            logger.warning("devices.yaml not found, using empty config")
            return {"sensors": {}, "relays": {}}

    async def initialize_connectors(self) -> bool:
        """
        MQTT ve Weather bağlantılarını başlat

        Returns:
            Başarılı ise True
        """
        success = True

        # MQTT Connector
        try:
            mqtt_config = self.settings.get("tts", {}).get("mqtt", {})
            self.mqtt_connector = TTSMQTTConnector(mqtt_config)

            if await self.mqtt_connector.connect():
                self.mqtt_connector.on_message(self._on_sensor_message)
                await self.mqtt_connector.subscribe()
                await self.mqtt_connector.start_listening()
                logger.info("MQTT connector initialized and listening")
            else:
                logger.error("MQTT connection failed")
                success = False
        except Exception as e:
            logger.error(f"MQTT initialization error: {e}")
            success = False

        # Weather Connector
        try:
            weather_config = self.settings.get("weather", {})
            self.weather_connector = WeatherConnector(weather_config)
            await self.weather_connector.connect()
            logger.info("Weather connector initialized")
        except Exception as e:
            logger.error(f"Weather initialization error: {e}")
            # Weather is optional, don't fail completely
            self.weather_connector = None

        self._initialized = True
        return success

    async def shutdown(self) -> None:
        """Bağlantıları kapat"""
        if self.mqtt_connector:
            try:
                await self.mqtt_connector.stop_listening()
                await self.mqtt_connector.disconnect()
                logger.info("MQTT connector disconnected")
            except Exception as e:
                logger.error(f"MQTT disconnect error: {e}")

        if self.weather_connector:
            try:
                await self.weather_connector.disconnect()
                logger.info("Weather connector disconnected")
            except Exception as e:
                logger.error(f"Weather disconnect error: {e}")

        self._initialized = False

    def on_sensor_data(self, callback: Callable[[dict], Any]) -> None:
        """
        Sensör verisi geldiğinde çağrılacak callback ekle

        Args:
            callback: Callback fonksiyonu (sync veya async)
        """
        self._sensor_callbacks.append(callback)

    async def _on_sensor_message(self, raw_message: dict) -> None:
        """
        MQTT mesajı geldiğinde çağrılır

        Args:
            raw_message: Ham TTS mesajı
        """
        try:
            # TTS mesajını parse et
            payload = raw_message.get("payload", {})

            # Process sensor data
            processed = self.sensor_processor.process(payload)
            if not processed:
                logger.warning("Could not process sensor message")
                return

            logger.debug(f"Processed sensor data from {processed.get('device_id')}")

            # Update trend analyzer
            for measurement in processed.get("measurements", []):
                name = measurement.get("name")
                value = measurement.get("value")
                if name and value is not None:
                    self.trend_analyzer.add_sample(name, value)

            # Update state
            await self._update_sensor_state(processed)

            # Call registered callbacks
            for callback in self._sensor_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(processed)
                    else:
                        callback(processed)
                except Exception as e:
                    logger.error(f"Sensor callback error: {e}")

        except Exception as e:
            logger.error(f"Error processing sensor message: {e}")

    async def _update_sensor_state(self, processed: dict) -> None:
        """
        Sensör state'ini güncelle

        Args:
            processed: İşlenmiş sensör verisi
        """
        try:
            updates = {"timestamp": datetime.utcnow().isoformat() + "Z"}

            for measurement in processed.get("measurements", []):
                name = measurement.get("name")
                if name:
                    updates[f"sensors.{name}"] = {
                        "value": measurement.get("value"),
                        "unit": measurement.get("unit"),
                        "status": measurement.get("status"),
                        "last_reading": processed.get("timestamp")
                    }

            # Also update trends
            for name in ["temperature", "humidity", "soil_moisture"]:
                trend = self.trend_analyzer.get_trend(name)
                updates[f"trends.{name}"] = {
                    "direction": trend.get("direction"),
                    "rate": trend.get("rate"),
                    "rate_formatted": trend.get("rate_formatted")
                }

            self.state_manager.update("current", updates)
            logger.debug("Sensor state updated")

        except Exception as e:
            logger.error(f"Error updating sensor state: {e}")

    async def update_weather(self) -> dict:
        """
        Hava durumu verisi al ve state'e kaydet

        Returns:
            Hava durumu verisi
        """
        result = {"current": None, "forecast": None, "error": None}

        if not self.weather_connector:
            result["error"] = "Weather connector not available"
            return result

        try:
            # Current weather
            current = await self.weather_connector.get_current()
            if "error" not in current:
                result["current"] = current
            else:
                result["error"] = current.get("error")

            # Forecast
            forecast = await self.weather_connector.get_forecast(days=3)
            if "error" not in forecast:
                result["forecast"] = forecast
            elif not result["error"]:
                result["error"] = forecast.get("error")

            # Update state
            if result["current"] or result["forecast"]:
                weather_state = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "current": result["current"],
                    "forecast": result["forecast"],
                    "last_update": datetime.utcnow().isoformat() + "Z"
                }
                self.state_manager.write("weather", weather_state)
                self._last_weather_update = datetime.utcnow()
                logger.info("Weather data updated")

        except Exception as e:
            logger.error(f"Error updating weather: {e}")
            result["error"] = str(e)

        return result

    async def collect_context(self) -> dict:
        """
        Brain için tüm veriyi topla

        Returns:
            Context dictionary
        """
        context = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "sensors": {},
            "trends": {},
            "weather": {},
            "device_states": {},
            "recent_decisions": []
        }

        try:
            # Current sensor state
            current_state = self.state_manager.read("current")
            context["sensors"] = current_state.get("sensors", {})
            context["trends"] = current_state.get("trends", {})
            context["data_quality"] = current_state.get("data_quality", {})

            # Add predictions from trend analyzer
            for sensor_type in ["temperature", "humidity", "soil_moisture"]:
                prediction = self.trend_analyzer.predict(sensor_type, hours_ahead=3)
                if prediction:
                    if sensor_type not in context["trends"]:
                        context["trends"][sensor_type] = {}
                    context["trends"][sensor_type]["prediction_3h"] = prediction

            # Weather data
            try:
                weather_state = self.state_manager.read("weather")
                context["weather"] = {
                    "current": weather_state.get("current"),
                    "forecast": weather_state.get("forecast"),
                    "last_update": weather_state.get("last_update")
                }
            except FileNotFoundError:
                logger.debug("Weather state not found")

            # Device states
            try:
                device_state = self.state_manager.read("device_states")
                context["device_states"] = device_state.get("devices", {})
                context["pending_actions"] = device_state.get("pending_actions", [])
            except FileNotFoundError:
                logger.debug("Device state not found")

            # Recent decisions (last 5)
            try:
                decisions_state = self.state_manager.read("decisions")
                all_decisions = decisions_state.get("decisions", [])
                context["recent_decisions"] = all_decisions[-5:] if all_decisions else []
            except FileNotFoundError:
                logger.debug("Decisions state not found")

        except Exception as e:
            logger.error(f"Error collecting context: {e}")
            context["error"] = str(e)

        return context

    def get_mqtt_status(self) -> dict:
        """MQTT bağlantı durumunu al"""
        if not self.mqtt_connector:
            return {"connected": False, "error": "Not initialized"}

        return {
            "connected": self.mqtt_connector.is_connected,
            "stats": self.mqtt_connector.stats
        }

    def get_weather_status(self) -> dict:
        """Weather API durumunu al"""
        if not self.weather_connector:
            return {"available": False, "error": "Not initialized"}

        return {
            "available": True,
            "connected": self.weather_connector.is_connected,
            "last_update": self._last_weather_update.isoformat() if self._last_weather_update else None
        }


if __name__ == "__main__":
    import asyncio

    async def test():
        print("DataCollector Test")
        print("=" * 50)

        # Create with minimal config for testing
        collector = DataCollector(
            settings_config={
                "tts": {"mqtt": {}},
                "weather": {"api_key": "test", "location": {"lat": 35.0, "lon": 33.0}}
            },
            device_config={"sensors": {}, "relays": {}},
            threshold_config={}
        )

        print(f"Initialized: {collector._initialized}")
        print(f"MQTT status: {collector.get_mqtt_status()}")
        print(f"Weather status: {collector.get_weather_status()}")

        # Test context collection
        context = await collector.collect_context()
        print(f"\nContext keys: {list(context.keys())}")

    asyncio.run(test())
