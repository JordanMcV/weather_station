"""Configuration for weather client."""

import logging
import os
from dataclasses import dataclass, field
from typing import FrozenSet


logger = logging.getLogger(__name__)

# Optional sensors that can be switched on and off. Temperature, humidity and
# pressure come from the BME280 and are always read.
ALL_OPTIONAL_SENSORS = frozenset({"wind", "rain"})

# The rain gauge does not register water, so it stays off until it is repaired.
DEFAULT_OPTIONAL_SENSORS = frozenset({"wind"})


def parse_enabled_sensors(raw: str) -> FrozenSet[str]:
    """Parse a comma separated sensor list and drop unknown names."""
    requested = {name.strip().lower() for name in raw.split(",") if name.strip()}
    unknown = requested - ALL_OPTIONAL_SENSORS
    if unknown:
        logger.warning(
            "[Weather Client] Ignoring unknown sensor names",
            extra={"unknown_sensors": sorted(unknown), "known_sensors": sorted(ALL_OPTIONAL_SENSORS)},
        )
    return frozenset(requested & ALL_OPTIONAL_SENSORS)


@dataclass
class Config:
    # Server connection
    server_url: str
    api_key: str

    # Upload behavior
    upload_interval: int = 300  # 5 minutes
    buffer_max_size: int = 1000
    retry_attempts: int = 5
    retry_base_delay: float = 1.0
    retry_max_delay: float = 60.0

    # Local storage
    database_path: str = "/tmp/weather.db"

    # Sensor settings
    sensor_read_interval: float = 15.0
    temperature_offset: float = -6.0
    enabled_sensors: FrozenSet[str] = field(default_factory=lambda: DEFAULT_OPTIONAL_SENSORS)

    # Health reporting
    health_upload_interval: int = 300

    # Station identity
    station_id: str = "piw"

    # Logging
    log_level: str = "INFO"

    # Dry run mode (no database, no uploads - just logging)
    dry_run: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        return cls(
            server_url=os.getenv("SERVER_URL", "http://localhost:8080"),
            api_key=os.getenv("API_KEY", "your-api-key-here"),
            upload_interval=int(os.getenv("UPLOAD_INTERVAL", "300")),
            buffer_max_size=int(os.getenv("BUFFER_MAX_SIZE", "1000")),
            retry_attempts=int(os.getenv("RETRY_ATTEMPTS", "5")),
            retry_base_delay=float(os.getenv("RETRY_BASE_DELAY", "1.0")),
            retry_max_delay=float(os.getenv("RETRY_MAX_DELAY", "60.0")),
            database_path=os.getenv("DATABASE_PATH", "/tmp/weather.db"),
            sensor_read_interval=float(os.getenv("SENSOR_READ_INTERVAL", "15.0")),
            temperature_offset=float(os.getenv("TEMPERATURE_OFFSET", "-6.0")),
            enabled_sensors=parse_enabled_sensors(
                os.getenv("ENABLED_SENSORS", ",".join(sorted(DEFAULT_OPTIONAL_SENSORS)))
            ),
            health_upload_interval=int(os.getenv("HEALTH_UPLOAD_INTERVAL", "300")),
            station_id=os.getenv("STATION_ID", "piw"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            dry_run=os.getenv("DRY_RUN", "false").strip().lower() in ("1", "true", "yes"),
        )
