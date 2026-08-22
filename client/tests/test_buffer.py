"""Tests for the SQLite upload buffer."""

from datetime import datetime, timedelta, timezone

import pytest

from weather_client.collector.buffer import SQLiteBuffer
from weather_client.models import WeatherReading


BASE = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)


def reading(offset_seconds=0, temperature=20.0):
    return WeatherReading(
        timestamp=BASE + timedelta(seconds=offset_seconds),
        temperature=temperature,
        humidity=50.0,
        pressure=1013.0,
    )


def test_add_reading_reports_success(db_path):
    buffer = SQLiteBuffer(db_path, max_size=10)
    assert buffer.add_reading(reading()) is True
    assert buffer.get_total_size() == 1
    assert buffer.get_buffer_size() == 1


def test_trimming_keeps_the_table_at_max_size(db_path):
    """The original DELETE ... ORDER BY ... LIMIT fails on stock CPython."""
    buffer = SQLiteBuffer(db_path, max_size=10)

    for index in range(40):
        assert buffer.add_reading(reading(index)) is True
        pending = buffer.get_pending_readings()
        buffer.mark_uploaded([item.row_id for item in pending])

    assert buffer.get_total_size() <= 10


def test_trimming_drops_pending_rows_when_nothing_uploaded(db_path):
    """A long outage must not grow the buffer without limit."""
    buffer = SQLiteBuffer(db_path, max_size=10)

    for index in range(50):
        buffer.add_reading(reading(index))

    assert buffer.get_total_size() == 10
    assert buffer.get_buffer_size() == 10

    # The rows kept are the newest ones.
    remaining = buffer.get_pending_readings()
    assert remaining[0].reading.timestamp == BASE + timedelta(seconds=40)


def test_mark_uploaded_does_not_affect_rows_sharing_a_timestamp(db_path):
    buffer = SQLiteBuffer(db_path, max_size=100)

    for _ in range(3):
        buffer.add_reading(reading(0))

    pending = buffer.get_pending_readings()
    assert len(pending) == 3

    buffer.mark_uploaded([pending[0].row_id])

    assert buffer.get_buffer_size() == 2


def test_mark_uploaded_accepts_an_empty_list(db_path):
    buffer = SQLiteBuffer(db_path, max_size=10)
    assert buffer.mark_uploaded([]) is True


def test_get_pending_readings_honours_the_limit(db_path):
    buffer = SQLiteBuffer(db_path, max_size=100)

    for index in range(20):
        buffer.add_reading(reading(index))

    limited = buffer.get_pending_readings(limit=5)
    assert len(limited) == 5
    # Oldest first, so a chunked upload drains in order.
    assert limited[0].reading.timestamp == BASE


def test_pending_readings_round_trip_optional_fields(db_path):
    buffer = SQLiteBuffer(db_path, max_size=10)
    full = WeatherReading(
        timestamp=BASE,
        temperature=21.0,
        humidity=52.0,
        pressure=1011.0,
        wind_speed=3.5,
        wind_direction=90.0,
        rain_total=0.5,
    )
    buffer.add_reading(full)

    stored = buffer.get_pending_readings()[0].reading
    assert stored.wind_speed == pytest.approx(3.5)
    assert stored.wind_direction == pytest.approx(90.0)
    assert stored.rain_total == pytest.approx(0.5)


def test_clear_uploaded_removes_only_uploaded_rows(db_path):
    buffer = SQLiteBuffer(db_path, max_size=100)

    for index in range(6):
        buffer.add_reading(reading(index))

    pending = buffer.get_pending_readings()
    buffer.mark_uploaded([item.row_id for item in pending[:4]])

    assert buffer.clear_uploaded() == 4
    assert buffer.get_total_size() == 2
