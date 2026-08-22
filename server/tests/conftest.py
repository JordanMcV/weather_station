"""Test fixtures for the weather server."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from weather_server.api import app as app_module
from weather_server.config import Config


API_KEY = "test-api-key"
BASE = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def config():
    return Config(api_key=API_KEY, influxdb_token="token")


@pytest.fixture
def influx():
    """A stand-in InfluxDB client that reports success."""
    with patch.object(app_module, "InfluxDBClient") as factory:
        client = factory.return_value
        client.write_batch = AsyncMock(return_value=True)
        client.write_health = AsyncMock(return_value=True)
        client.test_connection = AsyncMock(return_value=True)
        client.get_stations = AsyncMock(return_value=["piw"])
        client.get_stats = AsyncMock(return_value={"weather_readings_24h": 1})
        yield client


@pytest.fixture
def client(config, influx):
    return TestClient(app_module.create_app(config))


@pytest.fixture
def auth():
    return {"Authorization": f"Bearer {API_KEY}"}


def reading(offset_seconds=0, **overrides):
    """Build a valid reading payload, with room to break one field."""
    payload = {
        "timestamp": (BASE + timedelta(seconds=offset_seconds)).isoformat(),
        "temperature": 21.0,
        "humidity": 55.0,
        "pressure": 1013.0,
    }
    payload.update(overrides)
    return payload


def batch(readings, station_id="piw", batch_id="batch-1"):
    return {"readings": readings, "station_id": station_id, "batch_id": batch_id}


@pytest.fixture
def now():
    return datetime.now(timezone.utc)
