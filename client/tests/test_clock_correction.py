"""Tests for repairing timestamps recorded before NTP set the clock."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from weather_client.collector.buffer import SQLiteBuffer
from weather_client.models import WeatherReading


NS = 1_000_000_000


def make_reading(timestamp: datetime) -> WeatherReading:
    return WeatherReading(
        timestamp=timestamp,
        temperature=17.5,
        humidity=80.0,
        pressure=1013.0,
    )


@pytest.fixture
def buffer(tmp_path):
    return SQLiteBuffer(str(tmp_path / "weather.db"), max_size=1000)


def test_provisional_readings_are_never_uploaded(buffer):
    wrong_clock = datetime(2026, 8, 27, 16, 5, tzinfo=timezone.utc)
    buffer.add_reading(make_reading(wrong_clock), boot_id="b1", monotonic_ns=10 * NS, time_provisional=True)

    assert buffer.get_pending_readings() == []
    assert buffer.count_provisional() == 1


def test_trusted_readings_upload_normally(buffer):
    buffer.add_reading(make_reading(datetime.now(timezone.utc)), boot_id="b1", monotonic_ns=10 * NS)

    assert len(buffer.get_pending_readings()) == 1
    assert buffer.count_provisional() == 0


def test_same_boot_correction_is_exact(buffer):
    # Taken 300 seconds ago by the monotonic clock, but stamped an hour slow.
    wrong_clock = datetime(2026, 8, 27, 16, 5, tzinfo=timezone.utc)
    buffer.add_reading(make_reading(wrong_clock), boot_id="b1", monotonic_ns=100 * NS, time_provisional=True)

    now_wall = datetime(2026, 8, 27, 17, 30, tzinfo=timezone.utc)
    exact, inferred = buffer.correct_provisional("b1", now_wall, 400 * NS)

    assert (exact, inferred) == (1, 0)
    pending = buffer.get_pending_readings()
    assert len(pending) == 1
    assert pending[0].reading.timestamp == now_wall - timedelta(seconds=300)


def test_earlier_boot_inherits_the_offset_when_the_clock_is_continuous(buffer):
    # An earlier boot that never synced, running up to 16:04:45.
    for seconds in (15, 0):
        buffer.add_reading(
            make_reading(datetime(2026, 8, 27, 16, 4, 45, tzinfo=timezone.utc) - timedelta(seconds=seconds)),
            boot_id="b0",
            monotonic_ns=500 * NS,
            time_provisional=True,
        )

    # This boot restored that wrong clock and carried on from 16:05.
    buffer.add_reading(
        make_reading(datetime(2026, 8, 27, 16, 5, tzinfo=timezone.utc)),
        boot_id="b1",
        monotonic_ns=100 * NS,
        time_provisional=True,
    )

    now_wall = datetime(2026, 8, 27, 17, 30, tzinfo=timezone.utc)
    exact, inferred = buffer.correct_provisional("b1", now_wall, 400 * NS)

    assert (exact, inferred) == (1, 2)
    assert buffer.count_provisional() == 0

    # The offset measured on this boot is +1h20m, applied to the earlier boot too.
    offset = timedelta(hours=1, minutes=20)
    corrected = sorted(b.reading.timestamp for b in buffer.get_pending_readings())
    assert corrected[0] == datetime(2026, 8, 27, 16, 4, 30, tzinfo=timezone.utc) + offset


def test_earlier_boot_left_alone_when_the_clock_is_not_continuous(buffer):
    # A gap far wider than the reboot, so the offset cannot be assumed to carry.
    buffer.add_reading(
        make_reading(datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)),
        boot_id="b0",
        monotonic_ns=500 * NS,
        time_provisional=True,
    )
    buffer.add_reading(
        make_reading(datetime(2026, 8, 27, 16, 5, tzinfo=timezone.utc)),
        boot_id="b1",
        monotonic_ns=100 * NS,
        time_provisional=True,
    )

    exact, inferred = buffer.correct_provisional(
        "b1", datetime(2026, 8, 27, 17, 30, tzinfo=timezone.utc), 400 * NS
    )

    assert (exact, inferred) == (1, 0)
    assert buffer.count_provisional() == 1


def test_correction_does_nothing_without_a_reference_on_this_boot(buffer):
    buffer.add_reading(
        make_reading(datetime(2026, 8, 27, 16, 4, tzinfo=timezone.utc)),
        boot_id="b0",
        monotonic_ns=500 * NS,
        time_provisional=True,
    )

    exact, inferred = buffer.correct_provisional(
        "b1", datetime(2026, 8, 27, 17, 30, tzinfo=timezone.utc), 400 * NS
    )

    assert (exact, inferred) == (0, 0)
    assert buffer.count_provisional() == 1


def test_existing_database_gains_the_clock_columns(tmp_path):
    db_path = tmp_path / "old.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE weather_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                temperature REAL NOT NULL,
                humidity REAL NOT NULL,
                pressure REAL NOT NULL,
                wind_speed REAL,
                wind_direction REAL,
                rain_total REAL,
                created_at TEXT NOT NULL,
                uploaded BOOLEAN DEFAULT FALSE
            )
        """)
        conn.execute("""
            INSERT INTO weather_readings (timestamp, temperature, humidity, pressure, created_at)
            VALUES ('2026-08-27T12:00:00+00:00', 17.0, 80.0, 1013.0, '2026-08-27T12:00:00+00:00')
        """)
        conn.commit()

    buffer = SQLiteBuffer(str(db_path), max_size=1000)

    # The pre-existing reading survives and is treated as trustworthy.
    assert len(buffer.get_pending_readings()) == 1
    assert buffer.count_provisional() == 0
