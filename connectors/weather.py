"""
Sera Otonom - Weather Connector

OpenWeatherMap API'sinden hava durumu verisi alan modül
Retry logic, caching ve stats tracking ile
"""

import logging
import asyncio
from typing import Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import aiohttp
from .base import BaseConnector

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]  # Exponential backoff in seconds
RETRY_STATUS_CODES = {500, 502, 503, 504, 429}  # Server errors + rate limit


@dataclass
class WeatherData:
    """Weather data container"""
    temperature: Optional[float] = None
    humidity: Optional[int] = None
    description: str = ""
    wind_speed: Optional[float] = None
    clouds: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)
    location: str = ""
    forecast_high: Optional[float] = None
    forecast_low: Optional[float] = None
    rain_probability: Optional[float] = None


class WeatherConnector(BaseConnector):
    """OpenWeatherMap API Connector with retry logic and caching"""

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

        # Cache
        self._cache: Optional[WeatherData] = None
        self._cache_time: Optional[datetime] = None
        self._cache_ttl: timedelta = timedelta(minutes=15)

        # Stats
        self._stats = {
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "retries": 0,
            "cache_hits": 0
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        """Lazy HTTP session initialization"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
            self.is_connected = True
            logger.info("Weather API session created")
        return self.session

    async def connect(self) -> bool:
        """HTTP session oluştur"""
        try:
            if not self.api_key:
                logger.error("Weather API key not configured")
                return False
            await self._get_session()
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

    async def _request_with_retry(self, endpoint: str, params: dict) -> Optional[dict]:
        """
        Core retry logic for API requests

        Args:
            endpoint: API endpoint (e.g., "/weather")
            params: Query parameters

        Returns:
            JSON response dict or None on failure
        """
        session = await self._get_session()
        url = f"{self.BASE_URL}{endpoint}"
        self._stats["requests"] += 1

        for attempt in range(MAX_RETRIES):
            try:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        self._stats["successes"] += 1
                        return await response.json()
                    elif response.status in RETRY_STATUS_CODES:
                        logger.warning(
                            f"Weather API retryable error: {response.status}, "
                            f"attempt {attempt + 1}/{MAX_RETRIES}"
                        )
                        if attempt < MAX_RETRIES - 1:
                            self._stats["retries"] += 1
                            await asyncio.sleep(RETRY_DELAYS[attempt])
                            continue
                        else:
                            self._stats["failures"] += 1
                            error_text = await response.text()
                            logger.error(f"Weather API failed after retries: {response.status} - {error_text}")
                            return None
                    else:
                        # Non-retryable error
                        self._stats["failures"] += 1
                        error_text = await response.text()
                        logger.error(f"Weather API error: {response.status} - {error_text}")
                        return None

            except asyncio.TimeoutError:
                logger.warning(
                    f"Weather API timeout, attempt {attempt + 1}/{MAX_RETRIES}"
                )
                if attempt < MAX_RETRIES - 1:
                    self._stats["retries"] += 1
                    await asyncio.sleep(RETRY_DELAYS[attempt])
                    continue
                else:
                    self._stats["failures"] += 1
                    logger.error("Weather API failed: timeout after all retries")
                    return None

            except aiohttp.ClientError as e:
                logger.warning(
                    f"Weather API connection error: {e}, attempt {attempt + 1}/{MAX_RETRIES}"
                )
                if attempt < MAX_RETRIES - 1:
                    self._stats["retries"] += 1
                    await asyncio.sleep(RETRY_DELAYS[attempt])
                    continue
                else:
                    self._stats["failures"] += 1
                    logger.error(f"Weather API failed: {e}")
                    return None

            except Exception as e:
                self._stats["failures"] += 1
                logger.error(f"Weather API unexpected error: {e}")
                return None

        self._stats["failures"] += 1
        return None

    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid (within TTL)"""
        if self._cache is None or self._cache_time is None:
            return False
        return datetime.now() - self._cache_time < self._cache_ttl

    async def get_current_weather(self, force_refresh: bool = False) -> Optional[WeatherData]:
        """
        Get current weather with cache support

        Args:
            force_refresh: Force API call even if cache is valid

        Returns:
            WeatherData or None on failure
        """
        # Check cache
        if not force_refresh and self._is_cache_valid():
            self._stats["cache_hits"] += 1
            logger.debug("Weather cache hit")
            return self._cache

        params = {
            "lat": self.lat,
            "lon": self.lon,
            "appid": self.api_key,
            "units": "metric",
            "lang": "tr"
        }

        data = await self._request_with_retry("/weather", params)

        if data:
            # Parse response
            main = data.get("main", {})
            weather = data.get("weather", [{}])[0]
            wind = data.get("wind", {})
            clouds = data.get("clouds", {})

            weather_data = WeatherData(
                temperature=main.get("temp"),
                humidity=main.get("humidity"),
                description=weather.get("description", ""),
                wind_speed=wind.get("speed"),
                clouds=clouds.get("all"),
                timestamp=datetime.now(),
                location=data.get("name", ""),
                forecast_high=main.get("temp_max"),
                forecast_low=main.get("temp_min"),
                rain_probability=None  # Current weather doesn't include this
            )

            # Update cache
            self._cache = weather_data
            self._cache_time = datetime.now()

            return weather_data

        # Graceful degradation: return stale cache on failure
        if self._cache is not None:
            logger.warning("Weather API failed, returning stale cache")
            return self._cache

        return None

    async def get_forecast(self, days: int = 3) -> Optional[List[dict]]:
        """
        5-day forecast with simplified response

        Args:
            days: Number of days (max 5)

        Returns:
            List of forecast dicts or None on failure
        """
        params = {
            "lat": self.lat,
            "lon": self.lon,
            "appid": self.api_key,
            "units": "metric",
            "lang": "tr",
            "cnt": min(days * 8, 40)  # 8 entries per day (3-hour intervals)
        }

        data = await self._request_with_retry("/forecast", params)

        if data:
            forecasts = []
            for item in data.get("list", []):
                dt = datetime.fromtimestamp(item.get("dt", 0))
                main = item.get("main", {})
                weather = item.get("weather", [{}])[0]
                wind = item.get("wind", {})
                clouds = item.get("clouds", {})
                pop = item.get("pop", 0)

                forecasts.append({
                    "datetime": dt.isoformat(),
                    "temperature": main.get("temp"),
                    "temp_min": main.get("temp_min"),
                    "temp_max": main.get("temp_max"),
                    "humidity": main.get("humidity"),
                    "description": weather.get("description", ""),
                    "wind_speed": wind.get("speed"),
                    "clouds": clouds.get("all"),
                    "rain_probability": pop * 100  # Convert to percentage
                })

            return forecasts

        return None

    def get_stats(self) -> dict:
        """Return connector statistics"""
        return self._stats.copy()

    async def health_check(self) -> dict:
        """API erişimini kontrol et"""
        result = {
            "healthy": False,
            "service": "openweathermap",
            "timestamp": datetime.now().isoformat(),
            "stats": self.get_stats()
        }

        try:
            session = await self._get_session()

            url = f"{self.BASE_URL}/weather"
            params = {
                "lat": self.lat,
                "lon": self.lon,
                "appid": self.api_key,
                "units": "metric"
            }

            async with session.get(url, params=params) as response:
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
        Anlık hava durumunu al (legacy method, uses get_current_weather internally)

        Returns:
            Normalize edilmiş hava durumu verisi
        """
        weather_data = await self.get_current_weather()

        if weather_data:
            return self._map_weather_data_to_dict(weather_data)
        else:
            return {"error": "Failed to get weather data"}

    def _map_weather_data_to_dict(self, weather_data: WeatherData) -> dict:
        """Convert WeatherData to legacy dict format"""
        return {
            "timestamp": weather_data.timestamp.isoformat(),
            "source": "openweathermap",
            "location": {
                "name": weather_data.location,
                "lat": self.lat,
                "lon": self.lon
            },
            "temperature": {
                "current": weather_data.temperature,
                "min": weather_data.forecast_low,
                "max": weather_data.forecast_high,
                "unit": "°C"
            },
            "humidity": {
                "value": weather_data.humidity,
                "unit": "%"
            },
            "wind": {
                "speed": weather_data.wind_speed,
                "unit": "m/s"
            },
            "clouds": {
                "coverage": weather_data.clouds,
                "unit": "%"
            },
            "weather": {
                "description": weather_data.description
            }
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
        print(f"Stats: {connector.get_stats()}")

    asyncio.run(test())
