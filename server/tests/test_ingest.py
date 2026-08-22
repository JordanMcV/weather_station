"""Tests for weather batch ingestion and its status codes."""

from datetime import timedelta

from conftest import batch, reading


def test_a_valid_batch_is_stored(client, auth, influx):
    response = client.post("/api/v1/weather/batch", json=batch([reading()]), headers=auth)

    assert response.status_code == 200
    body = response.json()
    assert body["readings_count"] == 1
    assert body["rejected_count"] == 0
    influx.write_batch.assert_awaited_once()


def test_an_out_of_range_reading_is_dropped_not_rejected(client, auth, influx):
    """Rejecting the batch would jam the collector buffer for ever."""
    payload = batch([reading(temperature=999.0), reading(1)])

    response = client.post("/api/v1/weather/batch", json=payload, headers=auth)

    assert response.status_code == 200
    body = response.json()
    assert body["readings_count"] == 1
    assert body["rejected_count"] == 1

    stored = influx.write_batch.await_args.args[0]
    assert len(stored.readings) == 1


def test_a_batch_of_only_bad_readings_still_succeeds(client, auth, influx):
    response = client.post(
        "/api/v1/weather/batch", json=batch([reading(pressure=1.0)]), headers=auth
    )

    assert response.status_code == 200
    assert response.json()["readings_count"] == 0
    assert response.json()["rejected_count"] == 1
    influx.write_batch.assert_not_awaited()


def test_a_future_timestamp_is_dropped(client, auth, now):
    far_future = (now + timedelta(hours=3)).isoformat()

    response = client.post(
        "/api/v1/weather/batch",
        json=batch([reading(timestamp=far_future)]),
        headers=auth,
    )

    assert response.status_code == 200
    assert response.json()["rejected_count"] == 1


def test_a_timestamp_just_inside_the_window_is_kept(client, auth, now):
    soon = (now + timedelta(minutes=30)).isoformat()

    response = client.post(
        "/api/v1/weather/batch", json=batch([reading(timestamp=soon)]), headers=auth
    )

    assert response.status_code == 200
    assert response.json()["readings_count"] == 1


def test_a_very_old_timestamp_is_dropped(client, auth, now):
    ancient = (now - timedelta(days=45)).isoformat()

    response = client.post(
        "/api/v1/weather/batch", json=batch([reading(timestamp=ancient)]), headers=auth
    )

    assert response.status_code == 200
    assert response.json()["rejected_count"] == 1


def test_a_naive_timestamp_is_treated_as_utc(client, auth, now):
    """Collectors before the timezone fix sent naive timestamps."""
    naive = now.replace(tzinfo=None).isoformat()

    response = client.post(
        "/api/v1/weather/batch", json=batch([reading(timestamp=naive)]), headers=auth
    )

    assert response.status_code == 200
    assert response.json()["readings_count"] == 1


def test_an_empty_batch_is_a_client_error(client, auth):
    response = client.post("/api/v1/weather/batch", json=batch([]), headers=auth)

    assert response.status_code == 400


def test_a_batch_without_a_station_is_a_client_error(client, auth):
    response = client.post(
        "/api/v1/weather/batch", json=batch([reading()], station_id=""), headers=auth
    )

    assert response.status_code == 400


def test_a_missing_field_is_a_client_error(client, auth):
    response = client.post(
        "/api/v1/weather/batch",
        json={"readings": [{"temperature": 20.0}], "station_id": "piw", "batch_id": "b"},
        headers=auth,
    )

    assert response.status_code == 400
    assert "Invalid data format" in response.json()["detail"]


def test_a_storage_failure_is_a_server_error(client, auth, influx):
    """A deliberate 400 must not be reported as a 500, and vice versa."""
    influx.write_batch.return_value = False

    response = client.post("/api/v1/weather/batch", json=batch([reading()]), headers=auth)

    assert response.status_code == 500


def test_a_wrong_key_is_rejected(client):
    response = client.post(
        "/api/v1/weather/batch",
        json=batch([reading()]),
        headers={"Authorization": "Bearer wrong"},
    )

    assert response.status_code == 401


def test_a_missing_key_is_rejected(client):
    response = client.post("/api/v1/weather/batch", json=batch([reading()]))

    assert response.status_code == 401


def test_the_batch_id_survives_filtering(client, auth, influx):
    payload = batch([reading(), reading(1, humidity=500.0)], batch_id="keep-me")

    client.post("/api/v1/weather/batch", json=payload, headers=auth)

    assert influx.write_batch.await_args.args[0].batch_id == "keep-me"
