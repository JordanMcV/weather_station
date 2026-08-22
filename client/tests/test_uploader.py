"""Tests for upload encoding."""

import gzip
import json
from datetime import datetime, timedelta, timezone

from weather_client.collector.uploader import GZIP_MIN_READINGS, WeatherUploader
from weather_client.config import Config
from weather_client.models import WeatherBatch, WeatherReading


BASE = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)


def make_uploader():
    return WeatherUploader(Config(server_url="http://example.invalid:8080", api_key="k"))


def make_batch(count):
    readings = [
        WeatherReading(
            timestamp=BASE + timedelta(seconds=index),
            temperature=20.0,
            humidity=50.0,
            pressure=1013.0,
        )
        for index in range(count)
    ]
    return WeatherBatch(readings=readings, station_id="piw")


def test_small_payload_is_not_compressed():
    body, headers = make_uploader()._encode(json.dumps({"a": 1}), compress=False)

    assert headers == {}
    assert json.loads(body) == {"a": 1}


def test_compressed_payload_declares_the_encoding_and_round_trips():
    """The header used to claim gzip while the body stayed uncompressed."""
    uploader = make_uploader()
    payload = json.dumps({"a": 1})

    body, headers = uploader._encode(payload, compress=True)

    assert headers == {"Content-Encoding": "gzip"}
    assert json.loads(gzip.decompress(body)) == {"a": 1}


def test_a_batch_at_the_threshold_compresses():
    uploader = make_uploader()
    batch = make_batch(GZIP_MIN_READINGS)

    _, headers = uploader._encode(
        batch.to_json(), compress=len(batch.readings) >= GZIP_MIN_READINGS
    )

    assert headers == {"Content-Encoding": "gzip"}


def test_a_batch_below_the_threshold_stays_plain():
    uploader = make_uploader()
    batch = make_batch(GZIP_MIN_READINGS - 1)

    _, headers = uploader._encode(
        batch.to_json(), compress=len(batch.readings) >= GZIP_MIN_READINGS
    )

    assert headers == {}


def test_compression_actually_shrinks_a_real_batch():
    uploader = make_uploader()
    batch = make_batch(500)
    plain = batch.to_json().encode("utf-8")

    compressed, _ = uploader._encode(batch.to_json(), compress=True)

    assert len(compressed) < len(plain) / 4
