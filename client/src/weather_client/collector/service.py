"""Weather data collection service."""

import asyncio
import logging
import shutil
import subprocess
from datetime import datetime, timezone
import weatherhat
import psutil

from ..config import Config
from ..models import WeatherReading, WeatherBatch, SystemHealth
from .buffer import SQLiteBuffer
from .clock import boot_id, clock_is_synced, monotonic_ns
from .uploader import WeatherUploader


logger = logging.getLogger(__name__)

IW_SEARCH_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


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
        self.tasks = []
        self.boot_id = boot_id()

    async def start(self):
        """Start the weather collection service."""
        logger.info("Starting weather collector...")
        self.running = True

        logger.info(f"Optional sensors enabled: {sorted(self.config.enabled_sensors) or 'none'}")

        # Start background tasks
        if self.config.dry_run:
            # In dry-run mode, only collect readings (no upload task)
            self.tasks = [
                asyncio.create_task(self._collect_readings()),
            ]
        else:
            # Normal mode: collect, upload readings and report health
            self.tasks = [
                asyncio.create_task(self._collect_readings()),
                asyncio.create_task(self._upload_readings()),
                asyncio.create_task(self._upload_health()),
            ]

        try:
            await asyncio.gather(*self.tasks)
        except asyncio.CancelledError:
            logger.info("Weather collector stopped")
        finally:
            self.running = False

    async def stop(self):
        """Stop the weather collection service."""
        if not self.running:
            return

        logger.info("Stopping weather collector...")
        self.running = False

        # Cancel all running tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()

        # Wait for tasks to finish cancellation
        if self.tasks:
            try:
                await asyncio.gather(*self.tasks, return_exceptions=True)
            except Exception as e:
                logger.debug(f"Task cancellation completed: {e}")

        if self.uploader:
            await self.uploader.close()

        self._stop_sensor_polling()

        logger.info("Weather collector stopped successfully")

    def _stop_sensor_polling(self):
        """Stop the WeatherHAT interrupt polling thread.

        The library starts that thread without the daemon flag and only clears
        its loop condition from __del__, which the interpreter does not run in
        time. The interpreter then waits for the thread at shutdown, so the
        process never exits and systemd kills it after the stop timeout.
        """
        thread = getattr(self.sensor, "_poll_thread", None)
        if thread is None:
            return

        self.sensor._polling = False
        thread.join(timeout=5)
        if thread.is_alive():
            logger.warning("WeatherHAT polling thread did not stop within 5 seconds")

    async def _collect_readings(self):
        """Continuously collect weather readings from the sensor."""
        logger.info(f"Starting sensor reading loop (interval: {self.config.sensor_read_interval}s)")

        # The BME280 reports its register contents before the first conversion
        # finishes, which always fails validation and logs a misleading warning.
        # Prime the sensor and discard that first result.
        try:
            self.sensor.update(10)
            await asyncio.sleep(1)
            logger.debug("Discarded the first sensor reading while the BME280 settles")
        except Exception as e:
            logger.warning(f"Could not prime the sensor: {e}")

        while self.running:
            try:
                # Update sensor readings
                self.sensor.update(10)

                # Create weather reading
                reading = WeatherReading(
                    timestamp=datetime.now(timezone.utc),
                    temperature=self.sensor.temperature,
                    humidity=self.sensor.humidity,
                    pressure=self.sensor.pressure,
                    **self._read_optional_sensors(),
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
                        # Normal mode: store in buffer. A reading taken before
                        # NTP set the clock keeps its monotonic time, which is
                        # what recovers its true timestamp later.
                        if self.buffer.add_reading(
                            reading,
                            boot_id=self.boot_id,
                            monotonic_ns=monotonic_ns(),
                            time_provisional=not clock_is_synced(),
                        ):
                            logger.debug(f"Added reading: T={reading.temperature:.1f}°C, H={reading.humidity:.1f}%, P={reading.pressure:.1f}hPa")
                        else:
                            logger.error("Failed to add reading to buffer")
                else:
                    logger.warning(f"Invalid reading discarded: {reading}")

            except Exception as e:
                logger.error(f"Error collecting reading: {e}")

            await asyncio.sleep(self.config.sensor_read_interval)

    def _read_optional_sensors(self) -> dict:
        """Read the optional sensors that are enabled in configuration."""
        values = {}

        # The wind and rain counters only refresh on their own slower cycle.
        if not self.sensor.updated_wind_rain:
            return values

        if "wind" in self.config.enabled_sensors:
            values["wind_speed"] = self.sensor.wind_speed
            values["wind_direction"] = self.sensor.wind_direction
        if "rain" in self.config.enabled_sensors:
            values["rain_total"] = self.sensor.rain_total

        return values

    async def _upload_readings(self):
        """Periodically upload buffered readings to the server."""
        logger.info(f"Starting upload loop (interval: {self.config.upload_interval}s)")

        while self.running:
            try:
                self._correct_provisional_readings()
                await self._drain_buffer()
            except Exception as e:
                logger.error(f"Error in upload loop: {e}")

            await asyncio.sleep(self.config.upload_interval)

    def _correct_provisional_readings(self):
        """Repair timestamps recorded before NTP set the clock.

        Nothing happens until the clock is trustworthy, so a reading with a
        wrong timestamp is never uploaded.
        """
        if not clock_is_synced():
            waiting = self.buffer.count_provisional()
            if waiting:
                logger.warning(
                    "[Weather Client] Holding readings back, the clock is not set yet",
                    extra={"readings": waiting},
                )
            return

        if not self.buffer.count_provisional():
            return

        self.buffer.correct_provisional(
            current_boot_id=self.boot_id,
            now_wall=datetime.now(timezone.utc),
            now_monotonic_ns=monotonic_ns(),
        )

    async def _drain_buffer(self):
        """Upload the buffer in chunks until it empties or a chunk fails.

        A single request must stay well inside the HTTP timeout. After a long
        outage the buffer holds thousands of readings, and sending them all at
        once produces a request that cannot finish, which the collector would
        then retry for ever.
        """
        uploaded_total = 0

        while self.running:
            pending = self.buffer.get_pending_readings(limit=self.config.upload_batch_size)

            if not pending:
                if uploaded_total:
                    logger.info(f"Buffer drained, uploaded {uploaded_total} readings")
                else:
                    logger.debug("No pending readings to upload")
                return

            logger.info(f"Attempting to upload {len(pending)} readings")

            batch = WeatherBatch(
                readings=[item.reading for item in pending],
                station_id=self.config.station_id
            )

            if not await self.uploader.upload_batch(batch):
                logger.warning(
                    "[Weather Client] Chunk upload failed, will retry later",
                    extra={"uploaded_before_failure": uploaded_total},
                )
                return

            self.buffer.mark_uploaded([item.row_id for item in pending])
            self.last_upload = datetime.now(timezone.utc)
            uploaded_total += len(pending)
            logger.info(f"Successfully uploaded {len(pending)} readings")

    async def _upload_health(self):
        """Periodically report system health to the server."""
        logger.info(f"Starting health report loop (interval: {self.config.health_upload_interval}s)")

        while self.running:
            try:
                health = await asyncio.to_thread(self.get_status)
                if not await self.uploader.upload_health(health):
                    logger.warning("Failed to upload health snapshot, will retry later")
            except Exception as e:
                logger.error(f"Error in health report loop: {e}")

            await asyncio.sleep(self.config.health_upload_interval)

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

            wifi_signal, wifi_tx_bitrate, wifi_tx_retries = self._read_wifi_stats()

            return SystemHealth(
                timestamp=datetime.now(timezone.utc),
                station_id=self.config.station_id,
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                disk_percent=disk.percent,
                temperature=cpu_temp,
                network_connected=network_connected,
                last_upload=self.last_upload,
                buffer_size=buffer_size,
                wifi_signal_dbm=wifi_signal,
                wifi_tx_bitrate_mbps=wifi_tx_bitrate,
                wifi_tx_retries=wifi_tx_retries,
            )
        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            buffer_size = 0 if self.config.dry_run else (self.buffer.get_buffer_size() if self.buffer else 0)
            return SystemHealth(
                timestamp=datetime.now(timezone.utc),
                station_id=self.config.station_id,
                cpu_percent=0.0,
                memory_percent=0.0,
                disk_percent=0.0,
                network_connected=False,
                buffer_size=buffer_size,
            )

    def _read_wifi_stats(self) -> tuple:
        """Read the wireless signal level, retry count and transmit bitrate.

        Returns (signal_dbm, tx_bitrate_mbps, tx_retries). Any value the host
        cannot supply comes back as None.
        """
        interface = None
        signal_dbm = None
        tx_retries = None
        try:
            with open("/proc/net/wireless", "r") as f:
                for line in f.readlines()[2:]:
                    name, _, values = line.partition(":")
                    fields = values.split()
                    if len(fields) < 8:
                        continue
                    interface = name.strip()
                    signal_dbm = float(fields[2].rstrip("."))
                    tx_retries = int(float(fields[7].rstrip(".")))
                    break
        except (FileNotFoundError, ValueError, IndexError):
            pass

        # Resolve iw against the standard directories rather than the inherited
        # PATH, which omits the sbin directories outside systemd.
        iw = shutil.which("iw", path=IW_SEARCH_PATH) if interface else None

        tx_bitrate_mbps = None
        if iw:
            try:
                output = subprocess.run(
                    [iw, "dev", interface, "link"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                ).stdout
                for line in output.splitlines():
                    if "tx bitrate:" in line:
                        tx_bitrate_mbps = float(line.split(":")[1].split()[0])
                        break
            except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                pass

        return signal_dbm, tx_bitrate_mbps, tx_retries

    def _test_network_connectivity(self) -> bool:
        """Test network connectivity to the server."""
        import socket
        from urllib.parse import urlparse

        parsed = urlparse(self.config.server_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        try:
            with socket.create_connection((host, port), timeout=5):
                return True
        except OSError:
            return False
