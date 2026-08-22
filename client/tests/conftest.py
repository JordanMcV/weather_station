"""Test fixtures for the weather client.

The WeatherHAT libraries only install on Linux and need the hardware, so stub
them before anything imports the collector.
"""

import sys
import types
from unittest.mock import MagicMock

import pytest


def _install_hardware_stubs():
    if "weatherhat" not in sys.modules:
        weatherhat = types.ModuleType("weatherhat")
        weatherhat.WeatherHAT = MagicMock(name="WeatherHAT")
        sys.modules["weatherhat"] = weatherhat

    if "st7789" not in sys.modules:
        st7789 = types.ModuleType("st7789")
        st7789.ST7789 = MagicMock(name="ST7789")
        sys.modules["st7789"] = st7789


_install_hardware_stubs()


class FakeSensor:
    """Stands in for weatherhat.WeatherHAT."""

    def __init__(self, updated_wind_rain=True):
        self.temperature = 18.0
        self.humidity = 55.0
        self.pressure = 1013.0
        self.wind_speed = 2.5
        self.wind_direction = 180.0
        self.rain_total = 1.5
        self.updated_wind_rain = updated_wind_rain
        self.temperature_offset = 0.0
        self.update_calls = []

    def update(self, interval):
        self.update_calls.append(interval)


@pytest.fixture
def fake_sensor():
    return FakeSensor()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "weather.db")
