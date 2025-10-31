"""Configuration for weather server."""

import os
from dataclasses import dataclass
from typing import Optional


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

    # Security
    api_key: str = "your-api-key-here"

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
            api_key=os.getenv("API_KEY", "your-api-key-here"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
