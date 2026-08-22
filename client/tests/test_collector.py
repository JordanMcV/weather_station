"""Tests for sensor selection and chunked draining."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from weather_client.collector.buffer import SQLiteBuffer
from weather_client.collector.service import WeatherCollector
from weather_client.config import Config
from weather_client.models import WeatherReading


BASE = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)


class RecordingUploader:
    """Captures batches instead of sending them."""

    def __init__(self, fail_after=None):
        self.batches = []
        self.fail_after = fail_after

    async def upload_batch(self, batch):
        if self.fail_after is not None and len(self.batches) >= self.fail_after:
            return False
        self.batches.append(batch)
        return True

    async def upload_health(self, health):
        return True

    async def close(self):
        return None


def make_collector(db_path, fake_sensor, enabled_sensors, batch_size=500, fail_after=None):
    config = Config(
        server_url="http://example.invalid:8080",
        api_key="k",
        database_path=db_path,
        enabled_sensors=enabled_sensors,
        upload_batch_size=batch_size,
        buffer_max_size=100000,
    )
    collector = WeatherCollector.__new__(WeatherCollector)
    collector.config = config
    collector.sensor = fake_sensor
    collector.buffer = SQLiteBuffer(db_path, config.buffer_max_size)
    collector.uploader = RecordingUploader(fail_after=fail_after)
    collector.running = True
    collector.last_upload = None
    collector.tasks = []
    return collector


def test_wind_enabled_rain_disabled(db_path, fake_sensor):
    collector = make_collector(db_path, fake_sensor, frozenset({"wind"}))

    values = collector._read_optional_sensors()

    assert values == {"wind_speed": 2.5, "wind_direction": 180.0}
    assert "rain_total" not in values


def test_both_optional_sensors_enabled(db_path, fake_sensor):
    collector = make_collector(db_path, fake_sensor, frozenset({"wind", "rain"}))

    values = collector._read_optional_sensors()

    assert values["rain_total"] == 1.5
    assert values["wind_speed"] == 2.5


def test_no_optional_sensors(db_path, fake_sensor):
    collector = make_collector(db_path, fake_sensor, frozenset())

    assert collector._read_optional_sensors() == {}


def test_optional_sensors_skipped_until_the_counter_refreshes(db_path, fake_sensor):
    fake_sensor.updated_wind_rain = False
    collector = make_collector(db_path, fake_sensor, frozenset({"wind", "rain"}))

    assert collector._read_optional_sensors() == {}


def test_drain_splits_the_backlog_into_chunks(db_path, fake_sensor):
    collector = make_collector(db_path, fake_sensor, frozenset(), batch_size=100)

    for index in range(250):
        collector.buffer.add_reading(
            WeatherReading(
                timestamp=BASE + timedelta(seconds=index),
                temperature=20.0,
                humidity=50.0,
                pressure=1013.0,
            )
        )

    asyncio.run(collector._drain_buffer())

    sizes = [len(batch.readings) for batch in collector.uploader.batches]
    assert sizes == [100, 100, 50]
    assert collector.buffer.get_buffer_size() == 0
    assert collector.last_upload is not None


def test_drain_stops_and_keeps_data_when_a_chunk_fails(db_path, fake_sensor):
    collector = make_collector(db_path, fake_sensor, frozenset(), batch_size=100, fail_after=1)

    for index in range(250):
        collector.buffer.add_reading(
            WeatherReading(
                timestamp=BASE + timedelta(seconds=index),
                temperature=20.0,
                humidity=50.0,
                pressure=1013.0,
            )
        )

    asyncio.run(collector._drain_buffer())

    # The first chunk succeeded, the second failed, so the rest stays buffered.
    assert len(collector.uploader.batches) == 1
    assert collector.buffer.get_buffer_size() == 150


def test_drain_does_nothing_on_an_empty_buffer(db_path, fake_sensor):
    collector = make_collector(db_path, fake_sensor, frozenset())

    asyncio.run(collector._drain_buffer())

    assert collector.uploader.batches == []
    assert collector.last_upload is None


def test_each_batch_carries_the_station_id(db_path, fake_sensor):
    collector = make_collector(db_path, fake_sensor, frozenset(), batch_size=2)

    for index in range(4):
        collector.buffer.add_reading(
            WeatherReading(
                timestamp=BASE + timedelta(seconds=index),
                temperature=20.0,
                humidity=50.0,
                pressure=1013.0,
            )
        )

    asyncio.run(collector._drain_buffer())

    assert {batch.station_id for batch in collector.uploader.batches} == {"piw"}
    # Every chunk needs its own batch id, for traceability in the server log.
    ids = [batch.batch_id for batch in collector.uploader.batches]
    assert len(set(ids)) == len(ids)
