"""
Sera Otonom - Sensor Processor

Ham sensör verilerini normalize eden ve valide eden modül
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class SensorProcessor:
    """Sensör veri işleyici"""

    def __init__(self, device_config: dict, threshold_config: Optional[dict] = None):
        """
        Processor'ı başlat

        Args:
            device_config: devices.yaml içeriği
            threshold_config: thresholds.yaml içeriği
        """
        self.device_config = device_config
        self.threshold_config = threshold_config or {}
        self._build_sensor_map()
        logger.info("SensorProcessor initialized")

    def _build_sensor_map(self) -> None:
        """Device config'den sensör haritası oluştur"""
        self.sensor_map: Dict[str, dict] = {}
        self.device_id_map: Dict[str, dict] = {}

        sensors = self.device_config.get("sensors", {})
        for sensor_id, sensor_data in sensors.items():
            device_id = sensor_data.get("device_id", "")
            self.sensor_map[sensor_id] = sensor_data
            if device_id:
                self.device_id_map[device_id] = sensor_data

    def process(self, raw_message: dict) -> Optional[dict]:
        """
        Ham TTS mesajını işle

        Args:
            raw_message: TTS MQTT mesajı

        Returns:
            Normalize edilmiş sensör verisi veya None (hata durumunda)
        """
        try:
            # TTS mesaj yapısı: end_device_ids, received_at, uplink_message
            device_ids = raw_message.get("end_device_ids", {})
            device_id = device_ids.get("device_id", "")
            dev_eui = device_ids.get("dev_eui", "")

            uplink = raw_message.get("uplink_message", {})
            decoded_payload = uplink.get("decoded_payload", {})
            received_at = raw_message.get("received_at", datetime.now().isoformat())

            # Device config'den sensör bilgisi al
            sensor_config = self.device_id_map.get(device_id)
            if not sensor_config:
                logger.warning(f"Unknown device_id: {device_id}")
                return None

            # Ölçümleri işle
            measurements: List[dict] = []
            for measurement in sensor_config.get("measurements", []):
                measurement_name = measurement.get("name", "")
                decoded_field = measurement.get("decoded_field", "")
                valid_range = measurement.get("valid_range", [])
                unit = measurement.get("unit", "")

                raw_value = decoded_payload.get(decoded_field)
                if raw_value is None:
                    continue

                # Değeri float'a çevir
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    logger.warning(f"Invalid value for {measurement_name}: {raw_value}")
                    continue

                # Validasyon
                is_valid = self.validate(measurement_name, value)
                status = self.determine_status(measurement_name, value)

                measurements.append({
                    "name": measurement_name,
                    "value": value,
                    "unit": unit,
                    "valid": is_valid,
                    "status": status,
                    "valid_range": valid_range
                })

            if not measurements:
                logger.warning(f"No valid measurements for device {device_id}")
                return None

            # Metadata
            rx_metadata = uplink.get("rx_metadata", [{}])
            first_rx = rx_metadata[0] if rx_metadata else {}

            return {
                "device_id": device_id,
                "dev_eui": dev_eui,
                "sensor_type": sensor_config.get("type", "unknown"),
                "location": sensor_config.get("location", "unknown"),
                "timestamp": received_at,
                "processed_at": datetime.now().isoformat(),
                "measurements": measurements,
                "metadata": {
                    "rssi": first_rx.get("rssi"),
                    "snr": first_rx.get("snr"),
                    "gateway_id": first_rx.get("gateway_ids", {}).get("gateway_id"),
                    "f_cnt": uplink.get("f_cnt"),
                    "f_port": uplink.get("f_port")
                }
            }

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return None

    def validate(self, sensor_type: str, value: Any) -> bool:
        """
        Değerin geçerli aralıkta olup olmadığını kontrol et

        Args:
            sensor_type: Sensör tipi (temperature, humidity, soil_moisture, light)
            value: Kontrol edilecek değer

        Returns:
            Değer geçerliyse True
        """
        try:
            value = float(value)
        except (TypeError, ValueError):
            return False

        # Device config'den valid_range kontrolü
        for sensor_id, sensor_data in self.sensor_map.items():
            for measurement in sensor_data.get("measurements", []):
                if measurement.get("name") == sensor_type:
                    valid_range = measurement.get("valid_range", [])
                    if len(valid_range) == 2:
                        return valid_range[0] <= value <= valid_range[1]

        # Fallback: threshold config'den kontrol
        threshold = self.threshold_config.get(sensor_type, {})
        critical_low = threshold.get("critical_low")
        critical_high = threshold.get("critical_high")

        if critical_low is not None and critical_high is not None:
            # Critical değerlerin biraz dışında olabilir (sensör hatası için margin)
            margin = (critical_high - critical_low) * 0.1
            return (critical_low - margin) <= value <= (critical_high + margin)

        return True  # Config yoksa varsayılan olarak geçerli kabul et

    def determine_status(self, sensor_type: str, value: Any) -> str:
        """
        Değerin durumunu belirle

        Args:
            sensor_type: Sensör tipi (temperature, humidity, soil_moisture, light)
            value: Kontrol edilecek değer

        Returns:
            Status string: "normal", "warning", "critical"
        """
        try:
            value = float(value)
        except (TypeError, ValueError):
            return "unknown"

        threshold = self._get_threshold_config(sensor_type)
        if not threshold:
            return "normal"  # Config yoksa normal kabul et

        optimal_range = threshold.get("optimal_range", [])
        warning_low = threshold.get("warning_low")
        warning_high = threshold.get("warning_high")
        critical_low = threshold.get("critical_low")
        critical_high = threshold.get("critical_high")

        # Critical kontrol
        if critical_low is not None and value <= critical_low:
            return "critical"
        if critical_high is not None and value >= critical_high:
            return "critical"

        # Warning kontrol
        if warning_low is not None and value <= warning_low:
            return "warning"
        if warning_high is not None and value >= warning_high:
            return "warning"

        # Optimal aralıkta mı?
        if len(optimal_range) == 2:
            if optimal_range[0] <= value <= optimal_range[1]:
                return "normal"
            else:
                # Optimal dışında ama warning değerlerinin içinde
                return "warning"

        return "normal"

    def _get_threshold_config(self, sensor_type: str) -> dict:
        """
        Sensör tipi için threshold config'i al

        Args:
            sensor_type: Sensör tipi

        Returns:
            Threshold config dictionary
        """
        return self.threshold_config.get(sensor_type, {})

    def get_status_summary(self, measurements: List[dict]) -> str:
        """
        Tüm ölçümler için özet status belirle

        Args:
            measurements: Ölçüm listesi

        Returns:
            En kötü status
        """
        statuses = [m.get("status", "normal") for m in measurements]

        if "critical" in statuses:
            return "critical"
        if "warning" in statuses:
            return "warning"
        return "normal"


if __name__ == "__main__":
    # Test with sample configs
    device_config = {
        "sensors": {
            "temp_humidity_01": {
                "device_id": "sera-temp-hum-01",
                "type": "temperature_humidity",
                "measurements": [
                    {"name": "temperature", "unit": "°C", "decoded_field": "temperature", "valid_range": [-10, 60]},
                    {"name": "humidity", "unit": "%", "decoded_field": "humidity", "valid_range": [0, 100]}
                ],
                "location": "sera_ic"
            }
        }
    }

    threshold_config = {
        "temperature": {
            "optimal_range": [20, 28],
            "warning_low": 15,
            "warning_high": 32,
            "critical_low": 10,
            "critical_high": 38
        }
    }

    processor = SensorProcessor(device_config, threshold_config)
    print(f"SensorProcessor: {processor}")
    print(f"Validate temperature 25: {processor.validate('temperature', 25)}")
    print(f"Status temperature 25: {processor.determine_status('temperature', 25)}")
    print(f"Status temperature 35: {processor.determine_status('temperature', 35)}")
    print(f"Status temperature 40: {processor.determine_status('temperature', 40)}")
