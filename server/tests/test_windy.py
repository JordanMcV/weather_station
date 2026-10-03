"""Tests for the Windy forwarding summary."""

from datetime import timedelta

from conftest import BASE

from weather_server.config import Config
from weather_server.windy import build_params


def record(offset_seconds, **fields):
    values = {"temperature": 20.0, "humidity": 60.0, "pressure": 1013.0}
    values.update(fields)
    return {"time": BASE + timedelta(seconds=offset_seconds), **values}


def test_readings_are_averaged_and_converted():
    records = [
        record(-60, temperature=20.0, pressure=1012.0, wind_speed=2.0, wind_direction=90),
        record(0, temperature=21.0, pressure=1014.0, wind_speed=4.0, wind_direction=180),
    ]

    params = build_params("abc", records, BASE)

    assert params == {
        "id": "abc",
        "ts": int(BASE.timestamp()),
        "temp": 20.5,
        "humidity": 60,
        "pressure": 101300,
        "wind": 3.0,
        "gust": 4.0,
        "winddir": 180,
    }


def test_stale_data_is_not_sent():
    assert build_params("abc", [record(-15 * 60)], BASE) is None


def test_old_readings_fall_out_of_the_average():
    records = [record(-15 * 60, temperature=5.0), record(0, temperature=20.0)]

    assert build_params("abc", records, BASE)["temp"] == 20.0


def test_a_future_timestamp_is_clamped_to_now():
    params = build_params("abc", [record(120)], BASE)

    assert params["ts"] == int(BASE.timestamp())


def test_missing_wind_is_left_out():
    params = build_params("abc", [record(0)], BASE)

    assert "wind" not in params
    assert "gust" not in params
    assert "winddir" not in params


def test_forwarding_needs_both_id_and_password():
    assert not Config(windy_station_id="abc").windy_enabled
    assert Config(windy_station_id="abc", windy_station_password="secret").windy_enabled


def test_precip_is_the_rain_over_the_last_hour():
    records = [
        record(-70 * 60, rain_total=5.0),
        record(-50 * 60, rain_total=0.2794),
        record(-20 * 60, rain_total=0.5588),
        record(0, rain_total=0.0),
    ]

    assert build_params("abc", records, BASE)["precip"] == 0.8


def test_precip_is_left_out_when_rain_is_not_recorded():
    assert "precip" not in build_params("abc", [record(-20 * 60), record(0)], BASE)


def test_rain_alone_does_not_make_stale_data_fresh():
    assert build_params("abc", [record(-20 * 60, rain_total=1.0)], BASE) is None
