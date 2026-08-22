"""Tests for gzip request handling, health ingestion and CORS."""

import gzip
import json
from datetime import timezone

from conftest import API_KEY, BASE, batch, reading
from fastapi.testclient import TestClient

from weather_server.api import app as app_module


def post_raw(client, body, extra_headers=None):
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    headers.update(extra_headers or {})
    return client.post("/api/v1/weather/batch", content=body, headers=headers)


def payload(count=20):
    return json.dumps(batch([reading(index) for index in range(count)]))


def test_a_gzipped_body_is_decompressed(client, influx):
    response = post_raw(
        client, gzip.compress(payload().encode()), {"Content-Encoding": "gzip"}
    )

    assert response.status_code == 200
    assert response.json()["readings_count"] == 20


def test_a_plain_body_still_works(client):
    response = post_raw(client, payload().encode())

    assert response.status_code == 200
    assert response.json()["readings_count"] == 20


def test_a_body_that_lies_about_gzip_is_accepted(client):
    """Collectors before the compression fix set the header without compressing."""
    response = post_raw(client, payload().encode(), {"Content-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.json()["readings_count"] == 20


def test_rubbish_is_still_refused(client):
    response = post_raw(client, b"not json and not gzip", {"Content-Encoding": "gzip"})

    assert response.status_code == 422


def test_authentication_runs_on_the_compressed_path(client):
    response = client.post(
        "/api/v1/weather/batch",
        content=gzip.compress(payload().encode()),
        headers={"Authorization": "Bearer wrong", "Content-Encoding": "gzip"},
    )

    assert response.status_code == 401


def test_health_snapshots_are_stored(client, auth, influx):
    snapshot = {
        "timestamp": BASE.isoformat(),
        "station_id": "piw",
        "cpu_percent": 12.5,
        "memory_percent": 44.8,
        "disk_percent": 45.0,
        "temperature": 42.1,
        "network_connected": True,
        "last_upload": BASE.isoformat(),
        "buffer_size": 12,
    }

    response = client.post("/api/v1/health/system", json=snapshot, headers=auth)

    assert response.status_code == 200
    influx.write_health.assert_awaited_once()


def test_a_health_snapshot_without_a_timestamp_is_a_client_error(client, auth):
    response = client.post("/api/v1/health/system", json={"station_id": "piw"}, headers=auth)

    assert response.status_code == 400


def test_the_health_endpoint_reports_influx_state(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_health_timestamps_carry_a_timezone(client):
    """Naive timestamps used to reach InfluxDB."""
    stamp = client.get("/api/v1/health").json()["timestamp"]

    from datetime import datetime

    assert datetime.fromisoformat(stamp).tzinfo is not None


def test_cors_is_off_by_default(client):
    response = client.get("/api/v1/health", headers={"Origin": "http://evil.example"})

    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


def test_cors_appears_only_for_a_configured_origin(config, influx):
    config.cors_allow_origins = ["http://dashboard.example"]
    scoped = TestClient(app_module.create_app(config))

    response = scoped.get(
        "/api/v1/health", headers={"Origin": "http://dashboard.example"}
    )

    assert response.headers["access-control-allow-origin"] == "http://dashboard.example"
