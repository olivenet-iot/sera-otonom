"""
Sera Otonom - Weather Connector

OpenWeatherMap API'sinden hava durumu verisi alan modül
"""

import logging
from typing import Optional, List
from datetime import datetime
import aiohttp
from .base import BaseConnector

logger = logging.getLogger(__name__)


class WeatherConnector(BaseConnector):
    """OpenWeatherMap API Connector"""

    BASE_URL = "https://api.openweathermap.org/data/2.5"

    def __init__(self, config: dict):
        """
        Weather connector'ı başlat

        Args:
            config: API config (provider, api_key, location)
        """
        super().__init__("weather")
        self.config = config
        self.api_key = config.get("api_key", "")
        self.lat = config.get("location", {}).get("lat", 0)
        self.lon = config.get("location", {}).get("lon", 0)
        self.session: Optional[aiohttp.ClientSession] = None

    async def connect(self) -> bool:
        """HTTP session oluştur"""
        try:
            if self.session is None or self.session.closed:
                timeout = aiohttp.ClientTimeout(total=30)
                self.session = aiohttp.ClientSession(timeout=timeout)
                self.is_connected = True
                logger.info("Weather API session created")
            return True
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            self.is_connected = False
            return False

    async def disconnect(self) -> bool:
        """HTTP session kapat"""
        try:
            if self.session and not self.session.closed:
                await self.session.close()
                logger.info("Weather API session closed")
            self.session = None
            self.is_connected = False
            return True
        except Exception as e:
            logger.error(f"Failed to close session: {e}")
            return False

    async def health_check(self) -> dict:
        """API erişimini kontrol et"""
        result = {
            "healthy": False,
            "service": "openweathermap",
            "timestamp": datetime.now().isoformat()
        }

        try:
            if not self.session or self.session.closed:
                await self.connect()

            # Simple API test with minimal data
            url = f"{self.BASE_URL}/weather"
            params = {
                "lat": self.lat,
                "lon": self.lon,
                "appid": self.api_key,
                "units": "metric"
            }

            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    result["healthy"] = True
                    result["status_code"] = 200
                else:
                    result["status_code"] = response.status
                    result["error"] = await response.text()

        except aiohttp.ClientError as e:
            result["error"] = f"Connection error: {str(e)}"
        except Exception as e:
            result["error"] = f"Unexpected error: {str(e)}"

        return result

    async def get_current(self) -> dict:
        """
        Anlık hava durumunu al

        Returns:
            Normalize edilmiş hava durumu verisi
        """
        try:
            if not self.session or self.session.closed:
                await self.connect()

            url = f"{self.BASE_URL}/weather"
            params = {
                "lat": self.lat,
                "lon": self.lon,
                "appid": self.api_key,
                "units": "metric",
                "lang": "tr"
            }

            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._map_current(data)
                else:
                    error_text = await response.text()
                    logger.error(f"Weather API error: {response.status} - {error_text}")
                    return {"error": f"API error: {response.status}"}

        except aiohttp.ClientError as e:
            logger.error(f"Weather API connection error: {e}")
            return {"error": f"Connection error: {str(e)}"}
        except Exception as e:
            logger.error(f"Weather API unexpected error: {e}")
            return {"error": f"Unexpected error: {str(e)}"}

    async def get_forecast(self, days: int = 3) -> dict:
        """
        Hava tahminini al

        Args:
            days: Kaç günlük tahmin (max 5)

        Returns:
            Normalize edilmiş hava tahmini
        """
        try:
            if not self.session or self.session.closed:
                await self.connect()

            # OpenWeatherMap free tier: 5 day / 3 hour forecast
            url = f"{self.BASE_URL}/forecast"
            params = {
                "lat": self.lat,
                "lon": self.lon,
                "appid": self.api_key,
                "units": "metric",
                "lang": "tr",
                "cnt": min(days * 8, 40)  # 8 entries per day (3-hour intervals)
            }

            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._map_forecast(data, days)
                else:
                    error_text = await response.text()
                    logger.error(f"Weather API forecast error: {response.status} - {error_text}")
                    return {"error": f"API error: {response.status}"}

        except aiohttp.ClientError as e:
            logger.error(f"Weather API forecast connection error: {e}")
            return {"error": f"Connection error: {str(e)}"}
        except Exception as e:
            logger.error(f"Weather API forecast unexpected error: {e}")
            return {"error": f"Unexpected error: {str(e)}"}

    def _map_current(self, data: dict) -> dict:
        """
        OpenWeatherMap current response'ını normalize et

        Args:
            data: Raw API response

        Returns:
            Normalize edilmiş veri
        """
        main = data.get("main", {})
        weather = data.get("weather", [{}])[0]
        wind = data.get("wind", {})
        clouds = data.get("clouds", {})
        sys_data = data.get("sys", {})

        return {
            "timestamp": datetime.now().isoformat(),
            "source": "openweathermap",
            "location": {
                "name": data.get("name", ""),
                "lat": self.lat,
                "lon": self.lon,
                "country": sys_data.get("country", "")
            },
            "temperature": {
                "current": main.get("temp"),
                "feels_like": main.get("feels_like"),
                "min": main.get("temp_min"),
                "max": main.get("temp_max"),
                "unit": "°C"
            },
            "humidity": {
                "value": main.get("humidity"),
                "unit": "%"
            },
            "pressure": {
                "value": main.get("pressure"),
                "unit": "hPa"
            },
            "wind": {
                "speed": wind.get("speed"),
                "direction": wind.get("deg"),
                "gust": wind.get("gust"),
                "unit": "m/s"
            },
            "clouds": {
                "coverage": clouds.get("all"),
                "unit": "%"
            },
            "weather": {
                "condition": weather.get("main", ""),
                "description": weather.get("description", ""),
                "icon": weather.get("icon", "")
            },
            "sun": {
                "sunrise": datetime.fromtimestamp(sys_data.get("sunrise", 0)).isoformat() if sys_data.get("sunrise") else None,
                "sunset": datetime.fromtimestamp(sys_data.get("sunset", 0)).isoformat() if sys_data.get("sunset") else None
            },
            "visibility": data.get("visibility")  # meters
        }

    def _map_forecast(self, data: dict, days: int) -> dict:
        """
        OpenWeatherMap forecast response'ını normalize et

        Args:
            data: Raw API response
            days: Requested days

        Returns:
            Normalize edilmiş tahmin verisi
        """
        city = data.get("city", {})
        forecasts: List[dict] = []

        for item in data.get("list", []):
            dt = datetime.fromtimestamp(item.get("dt", 0))
            main = item.get("main", {})
            weather = item.get("weather", [{}])[0]
            wind = item.get("wind", {})
            clouds = item.get("clouds", {})
            pop = item.get("pop", 0)  # Probability of precipitation

            forecasts.append({
                "datetime": dt.isoformat(),
                "temperature": {
                    "value": main.get("temp"),
                    "feels_like": main.get("feels_like"),
                    "min": main.get("temp_min"),
                    "max": main.get("temp_max"),
                    "unit": "°C"
                },
                "humidity": {
                    "value": main.get("humidity"),
                    "unit": "%"
                },
                "pressure": {
                    "value": main.get("pressure"),
                    "unit": "hPa"
                },
                "wind": {
                    "speed": wind.get("speed"),
                    "direction": wind.get("deg"),
                    "gust": wind.get("gust"),
                    "unit": "m/s"
                },
                "clouds": {
                    "coverage": clouds.get("all"),
                    "unit": "%"
                },
                "weather": {
                    "condition": weather.get("main", ""),
                    "description": weather.get("description", ""),
                    "icon": weather.get("icon", "")
                },
                "precipitation_probability": pop * 100  # Convert to percentage
            })

        return {
            "timestamp": datetime.now().isoformat(),
            "source": "openweathermap",
            "location": {
                "name": city.get("name", ""),
                "lat": self.lat,
                "lon": self.lon,
                "country": city.get("country", "")
            },
            "requested_days": days,
            "forecast_count": len(forecasts),
            "forecasts": forecasts
        }


if __name__ == "__main__":
    import asyncio

    async def test():
        connector = WeatherConnector({
            "api_key": "test",
            "location": {"lat": 35.1856, "lon": 33.3823}
        })
        print(f"Weather Connector: {connector}")
        print(f"Connected: {connector.is_connected}")

    asyncio.run(test())
