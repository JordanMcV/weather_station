"""Tests for client configuration and sensor selection."""

from weather_client.config import (
    ALL_OPTIONAL_SENSORS,
    DEFAULT_OPTIONAL_SENSORS,
    Config,
    parse_enabled_sensors,
)


def test_rain_is_disabled_by_default():
    assert "rain" not in DEFAULT_OPTIONAL_SENSORS
    assert "wind" in DEFAULT_OPTIONAL_SENSORS


def test_parse_accepts_both_sensors():
    assert parse_enabled_sensors("wind,rain") == ALL_OPTIONAL_SENSORS


def test_parse_ignores_case_and_padding():
    assert parse_enabled_sensors("  WIND , Rain ") == ALL_OPTIONAL_SENSORS


def test_parse_drops_unknown_names():
    assert parse_enabled_sensors("wind,lightning") == frozenset({"wind"})


def test_parse_empty_disables_every_optional_sensor():
    assert parse_enabled_sensors("") == frozenset()


def test_from_env_uses_defaults(monkeypatch):
    for name in ("ENABLED_SENSORS", "TEMPERATURE_OFFSET", "DRY_RUN", "UPLOAD_BATCH_SIZE"):
        monkeypatch.delenv(name, raising=False)

    config = Config.from_env()

    assert config.enabled_sensors == DEFAULT_OPTIONAL_SENSORS
    assert config.dry_run is False
    assert config.upload_batch_size == 500


def test_from_env_calibration_matches_the_dataclass_default(monkeypatch):
    """The two defaults disagreed once, so the environment path miscalibrated."""
    monkeypatch.delenv("TEMPERATURE_OFFSET", raising=False)
    assert Config.from_env().temperature_offset == Config(
        server_url="x", api_key="y"
    ).temperature_offset


def test_from_env_reads_overrides(monkeypatch):
    monkeypatch.setenv("ENABLED_SENSORS", "rain")
    monkeypatch.setenv("UPLOAD_BATCH_SIZE", "50")
    monkeypatch.setenv("DRY_RUN", "true")

    config = Config.from_env()

    assert config.enabled_sensors == frozenset({"rain"})
    assert config.upload_batch_size == 50
    assert config.dry_run is True


def test_dry_run_accepts_several_spellings(monkeypatch):
    for value in ("1", "true", "TRUE", "yes"):
        monkeypatch.setenv("DRY_RUN", value)
        assert Config.from_env().dry_run is True

    for value in ("0", "false", "no", ""):
        monkeypatch.setenv("DRY_RUN", value)
        assert Config.from_env().dry_run is False
