"""InfluxDB client for weather data storage."""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

from influxdb_client import InfluxDBClient as InfluxClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from ..config import Config
from ..models import WeatherBatch, WeatherReading, SystemHealth


logger = logging.getLogger(__name__)


class InfluxDBClient:
    def __init__(self, config: Config):
        self.config = config
        self.client = InfluxClient(
            url=config.influxdb_url,
            token=config.influxdb_token,
            org=config.influxdb_org
        )
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.query_api = self.client.query_api()

    async def test_connection(self) -> bool:
        """Test connection to InfluxDB."""
        try:
            # Try to ping the InfluxDB server
            health = self.client.health()
            return health.status == "pass"
        except Exception as e:
            logger.error(f"InfluxDB connection test failed: {e}")
            return False

    async def write_batch(self, batch: WeatherBatch) -> bool:
        """Write a batch of weather readings to InfluxDB."""
        try:
            points = []

            for reading in batch.readings:
                point = Point("weather") \
                    .tag("station_id", batch.station_id) \
                    .field("temperature", reading.temperature) \
                    .field("humidity", reading.humidity) \
                    .field("pressure", reading.pressure) \
                    .time(reading.timestamp)

                # Add optional fields if present
                if reading.wind_speed is not None:
                    point = point.field("wind_speed", reading.wind_speed)
                if reading.wind_direction is not None:
                    point = point.field("wind_direction", reading.wind_direction)
                if reading.rain_total is not None:
                    point = point.field("rain_total", reading.rain_total)

                points.append(point)

            # Write points to InfluxDB
            self.write_api.write(
                bucket=self.config.influxdb_bucket,
                record=points
            )

            logger.debug(f"Successfully wrote {len(points)} points to InfluxDB")
            return True

        except Exception as e:
            logger.error(f"Failed to write weather batch to InfluxDB: {e}")
            return False

    async def write_health(self, health: SystemHealth) -> bool:
        """Write system health metrics to InfluxDB."""
        try:
            point = Point("system_health") \
                .tag("station_id", health.station_id) \
                .field("cpu_percent", health.cpu_percent) \
                .field("memory_percent", health.memory_percent) \
                .field("disk_percent", health.disk_percent) \
                .field("network_connected", health.network_connected) \
                .field("buffer_size", health.buffer_size) \
                .time(health.timestamp)

            # Add optional fields
            if health.temperature is not None:
                point = point.field("cpu_temperature", health.temperature)
            if health.last_upload is not None:
                point = point.field("last_upload", health.last_upload.timestamp())

            self.write_api.write(
                bucket=self.config.influxdb_bucket,
                record=point
            )

            logger.debug(f"Successfully wrote health data to InfluxDB")
            return True

        except Exception as e:
            logger.error(f"Failed to write health data to InfluxDB: {e}")
            return False

    async def get_stations(self) -> List[str]:
        """Get list of all weather stations."""
        try:
            query = f'''
                from(bucket: "{self.config.influxdb_bucket}")
                |> range(start: -7d)
                |> filter(fn: (r) => r._measurement == "weather")
                |> group(columns: ["station_id"])
                |> distinct(column: "station_id")
                |> group()
                |> sort(columns: ["station_id"])
            '''

            result = self.query_api.query(query)
            stations = []

            for table in result:
                for record in table.records:
                    if record.get_value() not in stations:
                        stations.append(record.get_value())

            return stations

        except Exception as e:
            logger.error(f"Failed to get stations from InfluxDB: {e}")
            return []

    async def get_stats(self) -> Dict[str, Any]:
        """Get statistics about stored data."""
        try:
            # Get count of weather readings in the last 24 hours
            weather_query = f'''
                from(bucket: "{self.config.influxdb_bucket}")
                |> range(start: -24h)
                |> filter(fn: (r) => r._measurement == "weather")
                |> count()
            '''

            # Get count of health records in the last 24 hours
            health_query = f'''
                from(bucket: "{self.config.influxdb_bucket}")
                |> range(start: -24h)
                |> filter(fn: (r) => r._measurement == "system_health")
                |> count()
            '''

            weather_result = self.query_api.query(weather_query)
            health_result = self.query_api.query(health_query)

            weather_count = 0
            health_count = 0

            for table in weather_result:
                for record in table.records:
                    weather_count += record.get_value()

            for table in health_result:
                for record in table.records:
                    health_count += record.get_value()

            return {
                "weather_readings_24h": weather_count,
                "health_records_24h": health_count,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to get stats from InfluxDB: {e}")
            return {
                "weather_readings_24h": 0,
                "health_records_24h": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e)
            }

    def close(self):
        """Close the InfluxDB client."""
        if self.client:
            self.client.close()
