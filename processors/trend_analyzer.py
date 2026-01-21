"""
Sera Otonom - Trend Analyzer

Linear regression ile sensör verilerinden trend hesaplayan modül
Pure Python implementasyonu (numpy kullanmaz)
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Sample:
    """Tek bir ölçüm örneği"""
    value: float
    timestamp: datetime


class TrendAnalyzer:
    """Linear regression tabanlı trend hesaplayıcı"""

    # Trend yönü eşikleri (birim/saat)
    TREND_THRESHOLDS = {
        "temperature": 0.5,   # 0.5°C/saat altındaki değişimler "stable"
        "humidity": 2.0,      # 2%/saat
        "soil_moisture": 1.0, # 1%/saat
        "light": 50.0         # 50 lux/saat
    }

    # Birimler
    UNITS = {
        "temperature": "°C",
        "humidity": "%",
        "soil_moisture": "%",
        "light": "lux"
    }

    def __init__(self, window_hours: int = 6, min_samples: int = 3, max_samples: int = 1000):
        """
        Analyzer'ı başlat

        Args:
            window_hours: Trend penceresi (saat)
            min_samples: Minimum örnek sayısı
            max_samples: Maksimum tutulan örnek sayısı (memory limit)
        """
        self.window_hours = window_hours
        self.min_samples = min_samples
        self.max_samples = max_samples
        self.history: Dict[str, List[Sample]] = {}
        logger.info(f"TrendAnalyzer initialized with {window_hours}h window, min {min_samples} samples")

    def add_sample(self, sensor_type: str, value: float, timestamp: Optional[datetime] = None) -> None:
        """
        Yeni örnek ekle

        Args:
            sensor_type: Sensör tipi (temperature, humidity, etc.)
            value: Ölçüm değeri
            timestamp: Zaman damgası (None ise şimdiki zaman)
        """
        if timestamp is None:
            timestamp = datetime.now()

        if sensor_type not in self.history:
            self.history[sensor_type] = []

        self.history[sensor_type].append(Sample(value=value, timestamp=timestamp))

        # Eski örnekleri temizle
        self._cleanup_old_samples(sensor_type)

        logger.debug(f"Added sample for {sensor_type}: {value} at {timestamp}")

    def _cleanup_old_samples(self, sensor_type: str) -> None:
        """
        Eski örnekleri temizle

        Args:
            sensor_type: Sensör tipi
        """
        if sensor_type not in self.history:
            return

        samples = self.history[sensor_type]

        # Zaman bazlı temizlik
        cutoff_time = datetime.now() - timedelta(hours=self.window_hours)
        samples = [s for s in samples if s.timestamp > cutoff_time]

        # Sayı bazlı temizlik
        if len(samples) > self.max_samples:
            samples = samples[-self.max_samples:]

        self.history[sensor_type] = samples

    def _calculate_linear_regression(self, samples: List[Sample]) -> Tuple[float, float, float]:
        """
        Pure Python linear regression hesapla

        Args:
            samples: Örnek listesi

        Returns:
            (slope, intercept, r_squared)
        """
        if len(samples) < 2:
            return 0.0, 0.0, 0.0

        # x = timestamp (saat cinsinden), y = value
        base_time = samples[0].timestamp
        x_values = [(s.timestamp - base_time).total_seconds() / 3600 for s in samples]
        y_values = [s.value for s in samples]

        n = len(samples)

        # Ortalamalar
        x_mean = sum(x_values) / n
        y_mean = sum(y_values) / n

        # Kovaryans ve varyans
        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
        denominator = sum((x - x_mean) ** 2 for x in x_values)

        if denominator == 0:
            return 0.0, y_mean, 0.0

        slope = numerator / denominator
        intercept = y_mean - slope * x_mean

        # R-squared (determination coefficient)
        y_pred = [slope * x + intercept for x in x_values]
        ss_res = sum((y - yp) ** 2 for y, yp in zip(y_values, y_pred))
        ss_tot = sum((y - y_mean) ** 2 for y in y_values)

        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0.0

        return slope, intercept, r_squared

    def get_trend(self, sensor_type: str) -> dict:
        """
        Trend hesapla

        Args:
            sensor_type: Sensör tipi

        Returns:
            {
                "direction": "rising|falling|stable",
                "rate": float (birim/saat),
                "rate_formatted": "+2.5°C/hour",
                "confidence": float (0-1),
                "sample_count": int
            }
        """
        samples = self.history.get(sensor_type, [])

        if len(samples) < self.min_samples:
            return {
                "direction": "unknown",
                "rate": 0.0,
                "rate_formatted": "N/A",
                "confidence": 0.0,
                "sample_count": len(samples),
                "error": f"Insufficient samples (need {self.min_samples}, have {len(samples)})"
            }

        slope, intercept, r_squared = self._calculate_linear_regression(samples)

        # Trend yönünü belirle
        threshold = self.TREND_THRESHOLDS.get(sensor_type, 0.5)
        if abs(slope) < threshold:
            direction = "stable"
        elif slope > 0:
            direction = "rising"
        else:
            direction = "falling"

        # Formatla
        unit = self.UNITS.get(sensor_type, "")
        sign = "+" if slope >= 0 else ""
        rate_formatted = f"{sign}{slope:.2f}{unit}/hour"

        return {
            "direction": direction,
            "rate": slope,
            "rate_formatted": rate_formatted,
            "confidence": max(0.0, min(1.0, r_squared)),
            "sample_count": len(samples)
        }

    def predict(self, sensor_type: str, hours_ahead: float) -> Optional[dict]:
        """
        Gelecek değeri tahmin et

        Args:
            sensor_type: Sensör tipi
            hours_ahead: Kaç saat sonrası

        Returns:
            {
                "predicted_value": float,
                "prediction_time": datetime ISO string,
                "confidence": float,
                "current_value": float
            }
            veya None (yeterli veri yoksa)
        """
        samples = self.history.get(sensor_type, [])

        if len(samples) < self.min_samples:
            return None

        slope, intercept, r_squared = self._calculate_linear_regression(samples)

        # Son değer ve tahmin
        last_sample = samples[-1]
        base_time = samples[0].timestamp
        current_hours = (last_sample.timestamp - base_time).total_seconds() / 3600
        future_hours = current_hours + hours_ahead

        predicted_value = slope * future_hours + intercept
        prediction_time = last_sample.timestamp + timedelta(hours=hours_ahead)

        # Confidence r_squared'e göre azalır ve zaman uzadıkça daha da düşer
        time_factor = max(0.5, 1.0 - (hours_ahead / 24))  # 24 saat sonrası için %50 düşüş
        confidence = r_squared * time_factor

        return {
            "predicted_value": round(predicted_value, 2),
            "prediction_time": prediction_time.isoformat(),
            "confidence": round(max(0.0, min(1.0, confidence)), 2),
            "current_value": last_sample.value,
            "hours_ahead": hours_ahead
        }

    def get_summary(self, sensor_type: str) -> dict:
        """
        Trend özeti al

        Args:
            sensor_type: Sensör tipi

        Returns:
            Kapsamlı trend özeti
        """
        samples = self.history.get(sensor_type, [])
        trend = self.get_trend(sensor_type)

        if not samples:
            return {
                "sensor_type": sensor_type,
                "trend": trend,
                "statistics": None,
                "predictions": None
            }

        values = [s.value for s in samples]

        # İstatistikler
        statistics = {
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
            "latest": values[-1],
            "range": max(values) - min(values),
            "sample_count": len(samples)
        }

        if len(samples) >= 2:
            statistics["first_timestamp"] = samples[0].timestamp.isoformat()
            statistics["last_timestamp"] = samples[-1].timestamp.isoformat()
            duration = (samples[-1].timestamp - samples[0].timestamp).total_seconds() / 3600
            statistics["duration_hours"] = round(duration, 2)

        # Tahminler (1, 3, 6 saat)
        predictions = {}
        for hours in [1, 3, 6]:
            pred = self.predict(sensor_type, hours)
            if pred:
                predictions[f"{hours}h"] = pred

        return {
            "sensor_type": sensor_type,
            "unit": self.UNITS.get(sensor_type, ""),
            "trend": trend,
            "statistics": statistics,
            "predictions": predictions if predictions else None
        }

    def clear_history(self, sensor_type: Optional[str] = None) -> None:
        """
        Geçmişi temizle

        Args:
            sensor_type: Belirli sensör tipi (None ise tümü)
        """
        if sensor_type:
            self.history.pop(sensor_type, None)
            logger.info(f"Cleared history for {sensor_type}")
        else:
            self.history.clear()
            logger.info("Cleared all history")


if __name__ == "__main__":
    # Test
    analyzer = TrendAnalyzer(window_hours=6, min_samples=3)

    # Örnek veriler ekle (yükselen sıcaklık)
    base_time = datetime.now()
    for i in range(10):
        analyzer.add_sample(
            "temperature",
            20.0 + i * 0.5,  # 20, 20.5, 21, 21.5, ...
            base_time + timedelta(hours=i)
        )

    print("TrendAnalyzer Test")
    print("=" * 50)

    trend = analyzer.get_trend("temperature")
    print(f"\nTrend: {trend}")

    prediction = analyzer.predict("temperature", 2)
    print(f"\n2 saat sonra tahmin: {prediction}")

    summary = analyzer.get_summary("temperature")
    print(f"\nÖzet: {summary}")
