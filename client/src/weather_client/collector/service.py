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
        self.sensor = weatherhat.WeatherHAT()
        self.sensor.temperature_offset = config.temperature_offset

        # Only initialize buffer and uploader if not in dry-run mode
        if not config.dry_run:
            self.buffer = SQLiteBuffer(config.database_path, config.buffer_max_size)
            self.uploader = WeatherUploader(config)
        else:
            self.buffer = None
            self.uploader = None

        self.running = False
        self.last_upload = None

    async def start(self):
        """Start the weather collection service."""
        logger.info("Starting weather collector...")
        self.running = True

        # Start background tasks
        if self.config.dry_run:
            # In dry-run mode, only collect readings (no upload task)
            tasks = [
                asyncio.create_task(self._collect_readings()),
            ]
        else:
            # Normal mode: collect and upload
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

                # Validate reading
                if reading.validate():
                    if self.config.dry_run:
                        # Dry-run mode: just log the reading
                        logger.info(
                            f"📊 READING: "
                            f"T={reading.temperature:.1f}°C, "
                            f"H={reading.humidity:.1f}%, "
                            f"P={reading.pressure:.1f}hPa"
                            + (f", Wind={reading.wind_speed:.1f}m/s@{reading.wind_direction}°" if reading.wind_speed else "")
                            + (f", Rain={reading.rain_total:.1f}mm" if reading.rain_total else "")
                        )
                    else:
                        # Normal mode: store in buffer
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

            # In dry-run mode, use a default path for disk check
            disk_path = self.config.database_path if not self.config.dry_run else "/"
            disk = psutil.disk_usage(disk_path)

            # Try to get CPU temperature (Raspberry Pi specific)
            cpu_temp = None
            try:
                with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                    cpu_temp = float(f.read().strip()) / 1000.0
            except (FileNotFoundError, ValueError):
                pass

            # Test network connectivity (skip in dry-run mode)
            network_connected = False if self.config.dry_run else self._test_network_connectivity()

            # Get buffer size (0 in dry-run mode)
            buffer_size = 0 if self.config.dry_run else self.buffer.get_buffer_size()

            return SystemHealth(
                timestamp=datetime.utcnow(),
                station_id=self.config.station_id,
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                disk_percent=disk.percent,
                temperature=cpu_temp,
                network_connected=network_connected,
                last_upload=self.last_upload,
                buffer_size=buffer_size,
            )
        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            buffer_size = 0 if self.config.dry_run else (self.buffer.get_buffer_size() if self.buffer else 0)
            return SystemHealth(
                timestamp=datetime.utcnow(),
                station_id=self.config.station_id,
                cpu_percent=0.0,
                memory_percent=0.0,
                disk_percent=0.0,
                network_connected=False,
                buffer_size=buffer_size,
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
