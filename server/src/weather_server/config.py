"""Configuration for weather server."""

import os
from dataclasses import dataclass, field
from typing import List, Optional


def parse_origins(raw: str) -> List[str]:
    """Parse a comma separated list of allowed CORS origins."""
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@dataclass
class Config:
    # Server settings
    host: str = "0.0.0.0"
    port: int = 8080

    # InfluxDB connection
    influxdb_url: str = "http://localhost:8086"
    influxdb_token: Optional[str] = None
    influxdb_org: str = "weather"
    influxdb_bucket: str = "weather_data"

    # Timestamp acceptance window. The collector has no real time clock and
    # depends on NTP at boot, so a wrong clock must not pollute the database.
    max_timestamp_future_seconds: int = 3600
    max_timestamp_age_days: int = 30

    # Security
    api_key: str = "your-api-key-here"

    # Browser access. The collector is server to server, so CORS stays off
    # unless a browser client needs it.
    cors_allow_origins: List[str] = field(default_factory=list)

    # Logging
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        return cls(
            host=os.getenv("SERVER_HOST", "0.0.0.0"),
            port=int(os.getenv("SERVER_PORT", "8080")),
            influxdb_url=os.getenv("INFLUXDB_URL", "http://localhost:8086"),
            influxdb_token=os.getenv("INFLUXDB_TOKEN"),
            influxdb_org=os.getenv("INFLUXDB_ORG", "weather"),
            influxdb_bucket=os.getenv("INFLUXDB_BUCKET", "weather_data"),
            max_timestamp_future_seconds=int(os.getenv("MAX_TIMESTAMP_FUTURE_SECONDS", "3600")),
            max_timestamp_age_days=int(os.getenv("MAX_TIMESTAMP_AGE_DAYS", "30")),
            api_key=os.getenv("API_KEY", "your-api-key-here"),
            cors_allow_origins=parse_origins(os.getenv("CORS_ALLOW_ORIGINS", "")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
