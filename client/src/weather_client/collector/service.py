"""Weather data collection service."""

import asyncio
import logging
from datetime import datetime
import weatherhat
import psutil

from ..config import Config
from ..models import WeatherReading, WeatherBatch, SystemHealth
from .buffer import SQLiteBuffer
from .uploader import WeatherUploader


logger = logging.getLogger(__name__)


class WeatherCollector:
    def __init__(self, config: Config):
        self.config = config
        self.sensor = weatherhat.WeatherHat()
        self.sensor.temperature_offset = config.temperature_offset
        self.buffer = SQLiteBuffer(config.database_path, config.buffer_max_size)
        self.uploader = WeatherUploader(config)
        self.running = False
        self.last_upload = None

    async def start(self):
        """Start the weather collection service."""
        logger.info("Starting weather collector...")
        self.running = True

        # Start background tasks
        tasks = [
            asyncio.create_task(self._collect_readings()),
            asyncio.create_task(self._upload_readings()),
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Weather collector stopped")
        finally:
            self.running = False

    async def stop(self):
        """Stop the weather collection service."""
        logger.info("Stopping weather collector...")
        self.running = False

    async def _collect_readings(self):
        """Continuously collect weather readings from the sensor."""
        logger.info(f"Starting sensor reading loop (interval: {self.config.sensor_read_interval}s)")

        while self.running:
            try:
                # Update sensor readings
                self.sensor.update(10)

                # Create weather reading
                reading = WeatherReading(
                    timestamp=datetime.utcnow(),
                    temperature=self.sensor.temperature,
                    humidity=self.sensor.humidity,
                    pressure=self.sensor.pressure,
                    wind_speed=self.sensor.wind_speed if self.sensor.updated_wind_rain else None,
                    wind_direction=self.sensor.wind_direction if self.sensor.updated_wind_rain else None,
                    rain_total=self.sensor.rain_total if self.sensor.updated_wind_rain else None,
                )

                # Validate and store reading
                if reading.validate():
                    if self.buffer.add_reading(reading):
                        logger.debug(f"Added reading: T={reading.temperature:.1f}°C, H={reading.humidity:.1f}%, P={reading.pressure:.1f}hPa")
                    else:
                        logger.error("Failed to add reading to buffer")
                else:
                    logger.warning(f"Invalid reading discarded: {reading}")

            except Exception as e:
                logger.error(f"Error collecting reading: {e}")

            await asyncio.sleep(self.config.sensor_read_interval)

    async def _upload_readings(self):
        """Periodically upload buffered readings to the server."""
        logger.info(f"Starting upload loop (interval: {self.config.upload_interval}s)")

        while self.running:
            try:
                pending_readings = self.buffer.get_pending_readings()

                if pending_readings:
                    logger.info(f"Attempting to upload {len(pending_readings)} readings")

                    batch = WeatherBatch(
                        readings=pending_readings,
                        station_id=self.config.station_id
                    )

                    success = await self.uploader.upload_batch(batch)
                    if success:
                        self.buffer.mark_uploaded(pending_readings)
                        self.last_upload = datetime.utcnow()
                        logger.info(f"Successfully uploaded {len(pending_readings)} readings")
                    else:
                        logger.warning("Failed to upload readings, will retry later")
                else:
                    logger.debug("No pending readings to upload")

            except Exception as e:
                logger.error(f"Error in upload loop: {e}")

            await asyncio.sleep(self.config.upload_interval)

    def get_status(self) -> SystemHealth:
        """Get current system health status."""
        try:
            # Get system metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage(self.config.database_path)

            # Try to get CPU temperature (Raspberry Pi specific)
            cpu_temp = None
            try:
                with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                    cpu_temp = float(f.read().strip()) / 1000.0
            except (FileNotFoundError, ValueError):
                pass

            # Test network connectivity
            network_connected = self._test_network_connectivity()

            return SystemHealth(
                timestamp=datetime.utcnow(),
                station_id=self.config.station_id,
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                disk_percent=disk.percent,
                temperature=cpu_temp,
                network_connected=network_connected,
                last_upload=self.last_upload,
                buffer_size=self.buffer.get_buffer_size(),
            )
        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            return SystemHealth(
                timestamp=datetime.utcnow(),
                station_id=self.config.station_id,
                cpu_percent=0.0,
                memory_percent=0.0,
                disk_percent=0.0,
                network_connected=False,
                buffer_size=self.buffer.get_buffer_size(),
            )

    def _test_network_connectivity(self) -> bool:
        """Test network connectivity to the server."""
        try:
            # Simple connectivity test - try to resolve the server hostname
            import socket
            from urllib.parse import urlparse

            parsed = urlparse(self.config.server_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 80

            socket.setdefaulttimeout(5)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
            return True
        except (socket.error, socket.timeout):
            return False
