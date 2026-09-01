"""Data models for weather readings and system health."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any
import json
import uuid


@dataclass
class WeatherReading:
    timestamp: datetime
    temperature: float
    humidity: float
    pressure: float
    wind_speed: Optional[float] = None
    wind_direction: Optional[float] = None
    rain_total: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "temperature": self.temperature,
            "humidity": self.humidity,
            "pressure": self.pressure,
            "wind_speed": self.wind_speed,
            "wind_direction": self.wind_direction,
            "rain_total": self.rain_total,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WeatherReading":
        timestamp = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        return cls(
            timestamp=timestamp,
            temperature=float(data["temperature"]),
            humidity=float(data["humidity"]),
            pressure=float(data["pressure"]),
            wind_speed=float(data["wind_speed"]) if data.get("wind_speed") is not None else None,
            wind_direction=float(data["wind_direction"]) if data.get("wind_direction") is not None else None,
            rain_total=float(data["rain_total"]) if data.get("rain_total") is not None else None,
        )

    def validate(self) -> bool:
        """Validate sensor readings are within reasonable ranges."""
        if not (-50 <= self.temperature <= 60):  # °C
            return False
        if not (0 <= self.humidity <= 100):  # %
            return False
        if not (800 <= self.pressure <= 1200):  # hPa
            return False
        if self.wind_speed is not None and not (0 <= self.wind_speed <= 100):  # m/s
            return False
        if self.wind_direction is not None and not (0 <= self.wind_direction <= 360):  # degrees
            return False
        if self.rain_total is not None and not (0 <= self.rain_total <= 1000):  # mm
            return False
        return True


@dataclass
class WeatherBatch:
    readings: List[WeatherReading]
    station_id: str
    batch_id: str

    def __init__(self, readings: List[WeatherReading], station_id: str, batch_id: Optional[str] = None):
        self.readings = readings
        self.station_id = station_id
        self.batch_id = batch_id or str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "readings": [reading.to_dict() for reading in self.readings],
            "station_id": self.station_id,
            "batch_id": self.batch_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WeatherBatch":
        readings = [WeatherReading.from_dict(r) for r in data["readings"]]
        return cls(
            readings=readings,
            station_id=data["station_id"],
            batch_id=data["batch_id"],
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> "WeatherBatch":
        return cls.from_dict(json.loads(json_str))

    def validate(self) -> bool:
        """Validate all readings in the batch."""
        if not self.readings:
            return False
        if not self.station_id:
            return False
        return all(reading.validate() for reading in self.readings)


@dataclass
class SystemHealth:
    timestamp: datetime
    station_id: str
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    temperature: Optional[float] = None
    network_connected: bool = True
    last_upload: Optional[datetime] = None
    buffer_size: int = 0
    wifi_signal_dbm: Optional[float] = None
    wifi_tx_bitrate_mbps: Optional[float] = None
    wifi_tx_retries: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "station_id": self.station_id,
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "disk_percent": self.disk_percent,
            "temperature": self.temperature,
            "network_connected": self.network_connected,
            "last_upload": self.last_upload.isoformat() if self.last_upload else None,
            "buffer_size": self.buffer_size,
            "wifi_signal_dbm": self.wifi_signal_dbm,
            "wifi_tx_bitrate_mbps": self.wifi_tx_bitrate_mbps,
            "wifi_tx_retries": self.wifi_tx_retries,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SystemHealth":
        last_upload = data.get("last_upload")
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00")),
            station_id=data["station_id"],
            cpu_percent=data["cpu_percent"],
            memory_percent=data["memory_percent"],
            disk_percent=data["disk_percent"],
            temperature=data.get("temperature"),
            network_connected=data.get("network_connected", True),
            last_upload=datetime.fromisoformat(last_upload.replace("Z", "+00:00")) if last_upload else None,
            buffer_size=data.get("buffer_size", 0),
            wifi_signal_dbm=data.get("wifi_signal_dbm"),
            wifi_tx_bitrate_mbps=data.get("wifi_tx_bitrate_mbps"),
            wifi_tx_retries=data.get("wifi_tx_retries"),
        )


@dataclass
class HealthBatch:
    """A batch of health snapshots, shaped like WeatherBatch.

    Health snapshots buffer and upload exactly as readings do, so a bad link
    delays them instead of destroying them.
    """

    snapshots: List[SystemHealth]
    station_id: str
    batch_id: str

    def __init__(self, snapshots: List[SystemHealth], station_id: str, batch_id: Optional[str] = None):
        self.snapshots = snapshots
        self.station_id = station_id
        self.batch_id = batch_id or str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshots": [snapshot.to_dict() for snapshot in self.snapshots],
            "station_id": self.station_id,
            "batch_id": self.batch_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HealthBatch":
        return cls(
            snapshots=[SystemHealth.from_dict(s) for s in data["snapshots"]],
            station_id=data["station_id"],
            batch_id=data.get("batch_id"),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

