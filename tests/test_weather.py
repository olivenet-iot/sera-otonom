"""
Sera Otonom - Weather Connector Unit Tests

pytest ile weather connector testleri
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
import aiohttp

from connectors.weather import (
    WeatherConnector,
    WeatherData,
    MAX_RETRIES,
    RETRY_DELAYS,
    RETRY_STATUS_CODES
)


# ==================== WeatherData Tests ====================

class TestWeatherData:
    """WeatherData dataclass testleri"""

    def test_default_values(self):
        data = WeatherData()
        assert data.temperature is None
        assert data.humidity is None
        assert data.description == ""
        assert data.wind_speed is None
        assert data.clouds is None
        assert data.location == ""
        assert data.forecast_high is None
        assert data.forecast_low is None
        assert data.rain_probability is None

    def test_with_values(self):
        data = WeatherData(
            temperature=25.5,
            humidity=70,
            description="Sunny",
            wind_speed=5.2,
            clouds=20,
            location="Test City",
            forecast_high=28.0,
            forecast_low=18.0,
            rain_probability=10.0
        )
        assert data.temperature == 25.5
        assert data.humidity == 70
        assert data.description == "Sunny"
        assert data.wind_speed == 5.2
        assert data.clouds == 20
        assert data.location == "Test City"

    def test_timestamp_auto_generated(self):
        data = WeatherData()
        assert data.timestamp is not None
        assert isinstance(data.timestamp, datetime)


# ==================== WeatherConnector Init Tests ====================

class TestWeatherConnectorInit:
    """WeatherConnector initialization testleri"""

    def test_init(self):
        """Basic initialization"""
        config = {
            "api_key": "test_key",
            "location": {"lat": 35.18, "lon": 33.38}
        }
        connector = WeatherConnector(config)

        assert connector.api_key == "test_key"
        assert connector.lat == 35.18
        assert connector.lon == 33.38
        assert connector.session is None
        assert connector._cache is None
        assert connector._cache_time is None
        assert connector._stats["requests"] == 0

    def test_init_no_api_key(self):
        """Init without API key"""
        config = {
            "location": {"lat": 35.18, "lon": 33.38}
        }
        connector = WeatherConnector(config)

        assert connector.api_key == ""

    def test_init_no_location(self):
        """Init without location defaults to 0,0"""
        config = {"api_key": "test_key"}
        connector = WeatherConnector(config)

        assert connector.lat == 0
        assert connector.lon == 0

    def test_stats_initialized(self):
        """Stats should be initialized with zeros"""
        connector = WeatherConnector({"api_key": "test"})

        stats = connector.get_stats()
        assert stats["requests"] == 0
        assert stats["successes"] == 0
        assert stats["failures"] == 0
        assert stats["retries"] == 0
        assert stats["cache_hits"] == 0


# ==================== Connect Tests ====================

class TestWeatherConnectorConnect:
    """WeatherConnector connect testleri"""

    @pytest.mark.asyncio
    async def test_connect_no_api_key(self):
        """Connect fails without API key"""
        connector = WeatherConnector({"location": {"lat": 35.18, "lon": 33.38}})
        result = await connector.connect()

        assert result is False

    @pytest.mark.asyncio
    async def test_connect_with_api_key(self):
        """Connect succeeds with API key"""
        connector = WeatherConnector({
            "api_key": "test_key",
            "location": {"lat": 35.18, "lon": 33.38}
        })

        result = await connector.connect()

        assert result is True
        assert connector.session is not None
        assert connector.is_connected is True

        # Cleanup
        await connector.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Disconnect closes session"""
        connector = WeatherConnector({
            "api_key": "test_key",
            "location": {"lat": 35.18, "lon": 33.38}
        })

        await connector.connect()
        result = await connector.disconnect()

        assert result is True
        assert connector.session is None
        assert connector.is_connected is False


# ==================== Cache Tests ====================

class TestWeatherConnectorCache:
    """WeatherConnector cache testleri"""

    def test_cache_valid_empty(self):
        """Empty cache is invalid"""
        connector = WeatherConnector({"api_key": "test"})

        assert connector._is_cache_valid() is False

    def test_cache_valid_fresh(self):
        """Fresh cache is valid"""
        connector = WeatherConnector({"api_key": "test"})
        connector._cache = WeatherData(temperature=25)
        connector._cache_time = datetime.now()

        assert connector._is_cache_valid() is True

    def test_cache_valid_stale(self):
        """Stale cache is invalid"""
        connector = WeatherConnector({"api_key": "test"})
        connector._cache = WeatherData(temperature=25)
        connector._cache_time = datetime.now() - timedelta(minutes=20)

        assert connector._is_cache_valid() is False

    @pytest.mark.asyncio
    async def test_get_current_weather_cache_hit(self):
        """Cache hit increments counter"""
        connector = WeatherConnector({
            "api_key": "test_key",
            "location": {"lat": 35.18, "lon": 33.38}
        })

        # Setup cache
        connector._cache = WeatherData(temperature=25, location="Test")
        connector._cache_time = datetime.now()

        # Get weather (should hit cache)
        result = await connector.get_current_weather()

        assert result is not None
        assert result.temperature == 25
        assert connector._stats["cache_hits"] == 1

    @pytest.mark.asyncio
    async def test_get_current_weather_force_refresh(self):
        """Force refresh bypasses cache"""
        connector = WeatherConnector({
            "api_key": "test_key",
            "location": {"lat": 35.18, "lon": 33.38}
        })

        # Setup cache
        connector._cache = WeatherData(temperature=25, location="Test")
        connector._cache_time = datetime.now()

        # Mock the request
        with patch.object(connector, '_request_with_retry', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "main": {"temp": 30, "humidity": 60},
                "weather": [{"description": "Clear"}],
                "wind": {"speed": 5},
                "clouds": {"all": 10},
                "name": "New City"
            }

            result = await connector.get_current_weather(force_refresh=True)

            assert result.temperature == 30
            assert connector._stats["cache_hits"] == 0
            mock_request.assert_called_once()

        await connector.disconnect()


# ==================== Retry Tests ====================

class TestWeatherConnectorRetry:
    """WeatherConnector retry logic testleri"""

    @pytest.fixture
    def connector(self):
        return WeatherConnector({
            "api_key": "test_key",
            "location": {"lat": 35.18, "lon": 33.38}
        })

    @pytest.mark.asyncio
    async def test_retry_on_500(self, connector):
        """Retry on server error (500)"""
        call_count = [0]

        class MockCM:
            async def __aenter__(self_cm):
                call_count[0] += 1
                mock_response = Mock()
                if call_count[0] < 3:
                    mock_response.status = 500
                    mock_response.text = AsyncMock(return_value="Server Error")
                else:
                    mock_response.status = 200
                    mock_response.json = AsyncMock(return_value={"data": "test"})
                return mock_response
            async def __aexit__(self_cm, *args):
                pass

        mock_session_instance = Mock()
        mock_session_instance.get.return_value = MockCM()

        with patch.object(connector, '_get_session', new_callable=AsyncMock) as mock_get_session:
            mock_get_session.return_value = mock_session_instance

            # Patch sleep to speed up test
            with patch('connectors.weather.asyncio.sleep', new_callable=AsyncMock):
                result = await connector._request_with_retry("/weather", {"test": "param"})

        assert result == {"data": "test"}
        assert connector._stats["retries"] >= 1

        await connector.disconnect()

    @pytest.mark.asyncio
    async def test_retry_on_timeout(self, connector):
        """Retry on timeout"""
        call_count = [0]

        class MockCM:
            async def __aenter__(self_cm):
                call_count[0] += 1
                if call_count[0] < 3:
                    raise asyncio.TimeoutError()
                mock_response = Mock()
                mock_response.status = 200
                mock_response.json = AsyncMock(return_value={"data": "success"})
                return mock_response
            async def __aexit__(self_cm, *args):
                pass

        mock_session_instance = Mock()
        mock_session_instance.get.return_value = MockCM()

        with patch.object(connector, '_get_session', new_callable=AsyncMock) as mock_get_session:
            mock_get_session.return_value = mock_session_instance

            with patch('connectors.weather.asyncio.sleep', new_callable=AsyncMock):
                result = await connector._request_with_retry("/weather", {"test": "param"})

        assert result == {"data": "success"}
        assert connector._stats["retries"] >= 1

        await connector.disconnect()

    @pytest.mark.asyncio
    async def test_no_retry_on_400(self, connector):
        """No retry on client error (400)"""
        class MockCM:
            async def __aenter__(self_cm):
                mock_response = Mock()
                mock_response.status = 400
                mock_response.text = AsyncMock(return_value="Bad Request")
                return mock_response
            async def __aexit__(self_cm, *args):
                pass

        mock_session_instance = Mock()
        mock_session_instance.get.return_value = MockCM()

        with patch.object(connector, '_get_session', new_callable=AsyncMock) as mock_get_session:
            mock_get_session.return_value = mock_session_instance

            result = await connector._request_with_retry("/weather", {"test": "param"})

        assert result is None
        assert connector._stats["failures"] == 1
        assert connector._stats["retries"] == 0

        await connector.disconnect()

    @pytest.mark.asyncio
    async def test_retry_on_429_rate_limit(self, connector):
        """Retry on rate limit (429)"""
        assert 429 in RETRY_STATUS_CODES

    @pytest.mark.asyncio
    async def test_retry_exhausted(self, connector):
        """All retries exhausted returns None"""
        class MockCM:
            async def __aenter__(self_cm):
                mock_response = Mock()
                mock_response.status = 500
                mock_response.text = AsyncMock(return_value="Server Error")
                return mock_response
            async def __aexit__(self_cm, *args):
                pass

        mock_session_instance = Mock()
        mock_session_instance.get.return_value = MockCM()

        with patch.object(connector, '_get_session', new_callable=AsyncMock) as mock_get_session:
            mock_get_session.return_value = mock_session_instance

            with patch('connectors.weather.asyncio.sleep', new_callable=AsyncMock):
                result = await connector._request_with_retry("/weather", {"test": "param"})

        assert result is None
        assert connector._stats["failures"] == 1

        await connector.disconnect()


# ==================== Stale Cache Fallback Tests ====================

class TestWeatherConnectorStaleCache:
    """Stale cache fallback testleri"""

    @pytest.mark.asyncio
    async def test_stale_cache_on_failure(self):
        """Stale cache returned on API failure"""
        connector = WeatherConnector({
            "api_key": "test_key",
            "location": {"lat": 35.18, "lon": 33.38}
        })

        # Setup stale cache
        connector._cache = WeatherData(temperature=22, location="Cached City")
        connector._cache_time = datetime.now() - timedelta(minutes=30)  # Stale

        # Mock request to fail
        with patch.object(connector, '_request_with_retry', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = None

            result = await connector.get_current_weather()

            assert result is not None
            assert result.temperature == 22
            assert result.location == "Cached City"

        await connector.disconnect()


# ==================== Health Check Tests ====================

class TestWeatherConnectorHealthCheck:
    """Health check testleri"""

    @pytest.mark.asyncio
    async def test_health_check_structure(self):
        """Health check returns expected structure"""
        connector = WeatherConnector({
            "api_key": "test_key",
            "location": {"lat": 35.18, "lon": 33.38}
        })

        class MockCM:
            async def __aenter__(self_cm):
                mock_response = Mock()
                mock_response.status = 200
                return mock_response
            async def __aexit__(self_cm, *args):
                pass

        mock_session_instance = Mock()
        mock_session_instance.get.return_value = MockCM()

        with patch.object(connector, '_get_session', new_callable=AsyncMock) as mock_get_session:
            mock_get_session.return_value = mock_session_instance

            result = await connector.health_check()

        assert "healthy" in result
        assert "service" in result
        assert "timestamp" in result
        assert "stats" in result
        assert result["service"] == "openweathermap"

        await connector.disconnect()


# ==================== Stats Tests ====================

class TestWeatherConnectorStats:
    """Stats tracking testleri"""

    def test_get_stats(self):
        """Stats retrieval returns copy"""
        connector = WeatherConnector({"api_key": "test"})
        connector._stats["requests"] = 10
        connector._stats["successes"] = 8
        connector._stats["failures"] = 2

        stats = connector.get_stats()

        assert stats["requests"] == 10
        assert stats["successes"] == 8
        assert stats["failures"] == 2

        # Verify it's a copy
        stats["requests"] = 100
        assert connector._stats["requests"] == 10

    @pytest.mark.asyncio
    async def test_stats_incremented_on_success(self):
        """Stats incremented on successful request"""
        connector = WeatherConnector({
            "api_key": "test_key",
            "location": {"lat": 35.18, "lon": 33.38}
        })

        class MockCM:
            async def __aenter__(self_cm):
                mock_response = Mock()
                mock_response.status = 200
                mock_response.json = AsyncMock(return_value={"data": "test"})
                return mock_response
            async def __aexit__(self_cm, *args):
                pass

        mock_session_instance = Mock()
        mock_session_instance.get.return_value = MockCM()

        with patch.object(connector, '_get_session', new_callable=AsyncMock) as mock_get_session:
            mock_get_session.return_value = mock_session_instance

            await connector._request_with_retry("/weather", {})

        assert connector._stats["requests"] == 1
        assert connector._stats["successes"] == 1

        await connector.disconnect()


# ==================== Forecast Tests ====================

class TestWeatherConnectorForecast:
    """Forecast testleri"""

    @pytest.mark.asyncio
    async def test_get_forecast_success(self):
        """Get forecast returns list"""
        connector = WeatherConnector({
            "api_key": "test_key",
            "location": {"lat": 35.18, "lon": 33.38}
        })

        mock_data = {
            "list": [
                {
                    "dt": 1704067200,
                    "main": {"temp": 20, "temp_min": 18, "temp_max": 22, "humidity": 60},
                    "weather": [{"description": "Clear"}],
                    "wind": {"speed": 3},
                    "clouds": {"all": 5},
                    "pop": 0.1
                }
            ]
        }

        with patch.object(connector, '_request_with_retry', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_data

            result = await connector.get_forecast(days=1)

            assert result is not None
            assert len(result) == 1
            assert result[0]["temperature"] == 20
            assert result[0]["rain_probability"] == 10.0

        await connector.disconnect()

    @pytest.mark.asyncio
    async def test_get_forecast_failure(self):
        """Get forecast returns None on failure"""
        connector = WeatherConnector({
            "api_key": "test_key",
            "location": {"lat": 35.18, "lon": 33.38}
        })

        with patch.object(connector, '_request_with_retry', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = None

            result = await connector.get_forecast()

            assert result is None

        await connector.disconnect()


# ==================== Legacy Method Tests ====================

class TestWeatherConnectorLegacy:
    """Legacy get_current method testleri"""

    @pytest.mark.asyncio
    async def test_get_current_success(self):
        """get_current returns dict format"""
        connector = WeatherConnector({
            "api_key": "test_key",
            "location": {"lat": 35.18, "lon": 33.38}
        })

        with patch.object(connector, 'get_current_weather', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = WeatherData(
                temperature=25,
                humidity=60,
                description="Sunny",
                wind_speed=5,
                clouds=10,
                location="Test City"
            )

            result = await connector.get_current()

            assert "temperature" in result
            assert "humidity" in result
            assert result["temperature"]["current"] == 25
            assert result["source"] == "openweathermap"

        await connector.disconnect()

    @pytest.mark.asyncio
    async def test_get_current_failure(self):
        """get_current returns error dict on failure"""
        connector = WeatherConnector({
            "api_key": "test_key",
            "location": {"lat": 35.18, "lon": 33.38}
        })

        with patch.object(connector, 'get_current_weather', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            result = await connector.get_current()

            assert "error" in result

        await connector.disconnect()


# ==================== Configuration Tests ====================

class TestWeatherConfiguration:
    """Configuration constant testleri"""

    def test_max_retries(self):
        """MAX_RETRIES is 3"""
        assert MAX_RETRIES == 3

    def test_retry_delays(self):
        """RETRY_DELAYS is exponential backoff"""
        assert RETRY_DELAYS == [2, 4, 8]

    def test_retry_status_codes(self):
        """RETRY_STATUS_CODES includes expected codes"""
        assert 500 in RETRY_STATUS_CODES
        assert 502 in RETRY_STATUS_CODES
        assert 503 in RETRY_STATUS_CODES
        assert 504 in RETRY_STATUS_CODES
        assert 429 in RETRY_STATUS_CODES
        assert 400 not in RETRY_STATUS_CODES
        assert 401 not in RETRY_STATUS_CODES


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
