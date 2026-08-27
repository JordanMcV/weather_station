"""SQLite buffer for weather data storage and retrieval."""

import sqlite3
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from pathlib import Path

from ..models import WeatherReading


logger = logging.getLogger(__name__)


@dataclass
class BufferedReading:
    """A reading paired with its buffer row id, so uploads mark exact rows."""

    row_id: int
    reading: WeatherReading


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
                    uploaded BOOLEAN DEFAULT FALSE,
                    boot_id TEXT,
                    monotonic_ns INTEGER,
                    time_provisional INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp ON weather_readings(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_uploaded ON weather_readings(uploaded)
            """)
            self._add_missing_columns(conn)
            conn.commit()

    def _add_missing_columns(self, conn: sqlite3.Connection):
        """Add the clock columns to a database created before they existed."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(weather_readings)")}
        for name, definition in (
            ("boot_id", "TEXT"),
            ("monotonic_ns", "INTEGER"),
            ("time_provisional", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in existing:
                conn.execute(f"ALTER TABLE weather_readings ADD COLUMN {name} {definition}")
                logger.info(
                    "[Weather Client] Added buffer column",
                    extra={"column": name},
                )

    def add_reading(
        self,
        reading: WeatherReading,
        boot_id: str = "",
        monotonic_ns: Optional[int] = None,
        time_provisional: bool = False,
    ) -> bool:
        """Add a weather reading to the buffer.

        A reading taken before NTP set the clock is stored as provisional. It
        keeps the monotonic clock that produced it, which is what recovers its
        true timestamp later, and it stays out of uploads until then.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO weather_readings
                    (timestamp, temperature, humidity, pressure, wind_speed, wind_direction, rain_total, created_at,
                     boot_id, monotonic_ns, time_provisional)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    reading.timestamp.isoformat(),
                    reading.temperature,
                    reading.humidity,
                    reading.pressure,
                    reading.wind_speed,
                    reading.wind_direction,
                    reading.rain_total,
                    datetime.now(timezone.utc).isoformat(),
                    boot_id,
                    monotonic_ns,
                    1 if time_provisional else 0,
                ))
                conn.commit()

                # Maintain max size by removing oldest readings
                self._cleanup_old_readings(conn)

            return True
        except sqlite3.Error as e:
            logger.error(f"Failed to add reading to buffer: {e}")
            return False

    def get_pending_readings(self, limit: Optional[int] = None) -> List[BufferedReading]:
        """Get readings that haven't been uploaded yet, each with its row id."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = """
                    SELECT id, timestamp, temperature, humidity, pressure, wind_speed, wind_direction, rain_total
                    FROM weather_readings
                    WHERE uploaded = FALSE AND time_provisional = 0
                    ORDER BY timestamp ASC
                """
                params: List[int] = []
                if limit:
                    query += " LIMIT ?"
                    params.append(limit)

                cursor = conn.execute(query, params)
                buffered = []

                for row in cursor.fetchall():
                    reading = WeatherReading(
                        timestamp=datetime.fromisoformat(row[1]),
                        temperature=row[2],
                        humidity=row[3],
                        pressure=row[4],
                        wind_speed=row[5],
                        wind_direction=row[6],
                        rain_total=row[7]
                    )
                    buffered.append(BufferedReading(row_id=row[0], reading=reading))

                return buffered
        except sqlite3.Error as e:
            logger.error(f"Failed to get pending readings: {e}")
            return []

    def mark_uploaded(self, row_ids: List[int]) -> bool:
        """Mark buffer rows as uploaded by primary key."""
        if not row_ids:
            return True
        try:
            with sqlite3.connect(self.db_path) as conn:
                placeholders = ",".join("?" * len(row_ids))
                conn.execute(f"""
                    UPDATE weather_readings
                    SET uploaded = TRUE
                    WHERE id IN ({placeholders})
                """, row_ids)
                conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Failed to mark readings as uploaded: {e}")
            return False

    def count_provisional(self) -> int:
        """Count readings still waiting for a trustworthy timestamp."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM weather_readings WHERE time_provisional = 1"
                )
                return cursor.fetchone()[0]
        except sqlite3.Error:
            logger.error("[Weather Client] Failed to count provisional readings", exc_info=True)
            return 0

    def correct_provisional(
        self,
        current_boot_id: str,
        now_wall: datetime,
        now_monotonic_ns: int,
        max_inference_gap_seconds: int = 600,
    ) -> Tuple[int, int]:
        """Give provisional readings their true timestamps.

        Readings from this boot are corrected exactly. The monotonic clock
        counts real elapsed time whatever NTP does to the wall clock, so the
        true time of a reading is the time now, less the monotonic interval
        since it was taken.

        Readings from an earlier boot have no monotonic reference, because that
        clock restarts at zero on every boot. They inherit the offset measured
        here, but only when their timestamps run contiguously into this boot's
        own provisional readings. That is what happens after a power cut,
        because each boot restores the wrong clock the previous one recorded.

        Return the number corrected exactly and the number corrected by
        inference.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                own = conn.execute("""
                    SELECT id, timestamp, monotonic_ns
                    FROM weather_readings
                    WHERE time_provisional = 1 AND boot_id = ? AND monotonic_ns IS NOT NULL
                    ORDER BY monotonic_ns ASC
                """, (current_boot_id,)).fetchall()

                if not own:
                    return 0, 0

                offset: Optional[timedelta] = None
                earliest_stored: Optional[datetime] = None

                for row_id, stored, monotonic in own:
                    elapsed = timedelta(microseconds=(now_monotonic_ns - monotonic) / 1000)
                    true_timestamp = now_wall - elapsed
                    stored_timestamp = datetime.fromisoformat(stored)

                    if earliest_stored is None:
                        earliest_stored = stored_timestamp
                    offset = true_timestamp - stored_timestamp

                    conn.execute("""
                        UPDATE weather_readings
                        SET timestamp = ?, time_provisional = 0
                        WHERE id = ?
                    """, (true_timestamp.isoformat(), row_id))

                inferred = self._infer_earlier_boots(
                    conn, current_boot_id, offset, earliest_stored, max_inference_gap_seconds
                )
                conn.commit()

            logger.info(
                "[Weather Client] Corrected readings taken before the clock was set",
                extra={
                    "corrected_from_monotonic": len(own),
                    "corrected_by_inference": inferred,
                    "offset_seconds": round(offset.total_seconds(), 3) if offset else 0,
                },
            )
            return len(own), inferred
        except sqlite3.Error:
            logger.error("[Weather Client] Failed to correct provisional readings", exc_info=True)
            return 0, 0

    def _infer_earlier_boots(
        self,
        conn: sqlite3.Connection,
        current_boot_id: str,
        offset: Optional[timedelta],
        earliest_stored: Optional[datetime],
        max_inference_gap_seconds: int,
    ) -> int:
        """Apply this boot's offset to provisional readings from earlier boots.

        The offset only carries across a reboot when the wrong clock carried
        across it too. Contiguous timestamps are the evidence for that, so a
        gap wider than max_inference_gap_seconds leaves the readings alone.
        """
        if offset is None or earliest_stored is None:
            return 0

        rows = conn.execute("""
            SELECT id, timestamp
            FROM weather_readings
            WHERE time_provisional = 1 AND (boot_id IS NULL OR boot_id != ?)
        """, (current_boot_id,)).fetchall()

        if not rows:
            return 0

        latest_earlier = max(datetime.fromisoformat(row[1]) for row in rows)
        gap = (earliest_stored - latest_earlier).total_seconds()

        if not 0 <= gap <= max_inference_gap_seconds:
            logger.warning(
                "[Weather Client] Left readings from an earlier boot uncorrected, clock not continuous",
                extra={"readings": len(rows), "gap_seconds": round(gap, 3)},
            )
            return 0

        for row_id, stored in rows:
            corrected = datetime.fromisoformat(stored) + offset
            conn.execute("""
                UPDATE weather_readings
                SET timestamp = ?, time_provisional = 0
                WHERE id = ?
            """, (corrected.isoformat(), row_id))

        return len(rows)

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
        """Trim the buffer back to max_size, preferring uploaded rows."""
        cursor = conn.execute("SELECT COUNT(*) FROM weather_readings")
        total_count = cursor.fetchone()[0]

        if total_count <= self.max_size:
            return

        excess = total_count - self.max_size

        # SQLite is normally built without UPDATE/DELETE LIMIT support, so
        # select the rows to drop with a subquery instead.
        uploaded_removed = conn.execute("""
            DELETE FROM weather_readings
            WHERE id IN (
                SELECT id FROM weather_readings
                WHERE uploaded = TRUE
                ORDER BY created_at ASC
                LIMIT ?
            )
        """, (excess,)).rowcount

        still_excess = excess - uploaded_removed
        if still_excess <= 0:
            return

        # Nothing left that has been uploaded, so the server has been
        # unreachable for a long time. Drop the oldest readings anyway. Losing
        # the oldest data beats filling the disk and losing the station.
        pending_removed = conn.execute("""
            DELETE FROM weather_readings
            WHERE id IN (
                SELECT id FROM weather_readings
                ORDER BY created_at ASC
                LIMIT ?
            )
        """, (still_excess,)).rowcount

        if pending_removed:
            logger.warning(
                "[Weather Client] Buffer full of readings that never uploaded, dropped the oldest",
                extra={
                    "dropped_readings": pending_removed,
                    "buffer_max_size": self.max_size,
                },
            )

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
