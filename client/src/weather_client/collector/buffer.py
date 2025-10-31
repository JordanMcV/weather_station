"""SQLite buffer for weather data storage and retrieval."""

import sqlite3
import logging
from datetime import datetime
from typing import List, Optional
from pathlib import Path

from ..models import WeatherReading


logger = logging.getLogger(__name__)


class SQLiteBuffer:
    def __init__(self, db_path: str, max_size: int = 1000):
        self.db_path = Path(db_path)
        self.max_size = max_size
        self._init_database()

    def _init_database(self):
        """Initialize the SQLite database with required tables."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS weather_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    temperature REAL NOT NULL,
                    humidity REAL NOT NULL,
                    pressure REAL NOT NULL,
                    wind_speed REAL,
                    wind_direction REAL,
                    rain_total REAL,
                    created_at TEXT NOT NULL,
                    uploaded BOOLEAN DEFAULT FALSE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp ON weather_readings(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_uploaded ON weather_readings(uploaded)
            """)
            conn.commit()

    def add_reading(self, reading: WeatherReading) -> bool:
        """Add a weather reading to the buffer."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO weather_readings
                    (timestamp, temperature, humidity, pressure, wind_speed, wind_direction, rain_total, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    reading.timestamp.isoformat(),
                    reading.temperature,
                    reading.humidity,
                    reading.pressure,
                    reading.wind_speed,
                    reading.wind_direction,
                    reading.rain_total,
                    datetime.utcnow().isoformat()
                ))
                conn.commit()

                # Maintain max size by removing oldest readings
                self._cleanup_old_readings(conn)

            return True
        except sqlite3.Error as e:
            logger.error(f"Failed to add reading to buffer: {e}")
            return False

    def get_pending_readings(self, limit: Optional[int] = None) -> List[WeatherReading]:
        """Get readings that haven't been uploaded yet."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = """
                    SELECT timestamp, temperature, humidity, pressure, wind_speed, wind_direction, rain_total
                    FROM weather_readings
                    WHERE uploaded = FALSE
                    ORDER BY timestamp ASC
                """
                if limit:
                    query += f" LIMIT {limit}"

                cursor = conn.execute(query)
                readings = []

                for row in cursor.fetchall():
                    timestamp = datetime.fromisoformat(row[0])
                    reading = WeatherReading(
                        timestamp=timestamp,
                        temperature=row[1],
                        humidity=row[2],
                        pressure=row[3],
                        wind_speed=row[4],
                        wind_direction=row[5],
                        rain_total=row[6]
                    )
                    readings.append(reading)

                return readings
        except sqlite3.Error as e:
            logger.error(f"Failed to get pending readings: {e}")
            return []

    def mark_uploaded(self, readings: List[WeatherReading]) -> bool:
        """Mark readings as uploaded."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                timestamps = [r.timestamp.isoformat() for r in readings]
                placeholders = ",".join("?" * len(timestamps))
                conn.execute(f"""
                    UPDATE weather_readings
                    SET uploaded = TRUE
                    WHERE timestamp IN ({placeholders})
                """, timestamps)
                conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Failed to mark readings as uploaded: {e}")
            return False

    def get_buffer_size(self) -> int:
        """Get the current number of readings in the buffer."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM weather_readings WHERE uploaded = FALSE")
                return cursor.fetchone()[0]
        except sqlite3.Error as e:
            logger.error(f"Failed to get buffer size: {e}")
            return 0

    def get_total_size(self) -> int:
        """Get the total number of readings in the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM weather_readings")
                return cursor.fetchone()[0]
        except sqlite3.Error as e:
            logger.error(f"Failed to get total size: {e}")
            return 0

    def _cleanup_old_readings(self, conn: sqlite3.Connection):
        """Remove old uploaded readings to maintain max size."""
        cursor = conn.execute("SELECT COUNT(*) FROM weather_readings")
        total_count = cursor.fetchone()[0]

        if total_count > self.max_size:
            excess = total_count - self.max_size
            conn.execute("""
                DELETE FROM weather_readings
                WHERE uploaded = TRUE
                ORDER BY created_at ASC
                LIMIT ?
            """, (excess,))

    def clear_uploaded(self) -> int:
        """Clear all uploaded readings and return count removed."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM weather_readings WHERE uploaded = TRUE")
                count = cursor.fetchone()[0]
                conn.execute("DELETE FROM weather_readings WHERE uploaded = TRUE")
                conn.commit()
                return count
        except sqlite3.Error as e:
            logger.error(f"Failed to clear uploaded readings: {e}")
            return 0
