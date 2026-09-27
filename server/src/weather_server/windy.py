"""Forward current conditions to Windy Stations."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from .config import Config


logger = logging.getLogger(__name__)

WINDY_UPDATE_URL = "https://stations.windy.com/api/v2/observation/update"

# Windy wants current conditions, so summarise a short recent window and skip
# the upload when the collector has gone quiet rather than resend stale data.
SUMMARY_WINDOW = timedelta(minutes=10)


def build_params(station_id: str, records: List[Dict[str, Any]], now: datetime) -> Optional[Dict[str, Any]]:
    """Turn recent weather records into Windy query parameters.

    Each record holds a "time" and the stored fields. Averages smooth sensor
    noise, the strongest wind stands in for the gust, and the latest direction
    is sent as is. Returns None when there is nothing recent to report.
    """
    recent = [record for record in records if record["time"] >= now - SUMMARY_WINDOW]
    if not recent:
        return None

    def mean(field: str) -> Optional[float]:
        values = [record[field] for record in recent if record.get(field) is not None]
        return sum(values) / len(values) if values else None

    latest = max(recent, key=lambda record: record["time"])
    # Windy rejects a timestamp in the future.
    ts = min(latest["time"], now)

    params: Dict[str, Any] = {"id": station_id, "ts": int(ts.timestamp())}

    temperature = mean("temperature")
    if temperature is not None:
        params["temp"] = round(temperature, 1)
    humidity = mean("humidity")
    if humidity is not None:
        params["humidity"] = round(humidity)
    pressure = mean("pressure")
    if pressure is not None:
        params["pressure"] = round(pressure * 100)

    wind_speeds = [record["wind_speed"] for record in recent if record.get("wind_speed") is not None]
    if wind_speeds:
        params["wind"] = round(sum(wind_speeds) / len(wind_speeds), 1)
        params["gust"] = round(max(wind_speeds), 1)
    if latest.get("wind_direction") is not None:
        params["winddir"] = round(latest["wind_direction"])

    return params


class WindyForwarder:
    def __init__(self, config: Config, influx_client):
        self.config = config
        self.influx_client = influx_client
        self.logger_context = {
            "source_station": config.windy_source_station,
            "windy_station": config.windy_station_id,
        }

    async def run(self):
        async with httpx.AsyncClient(timeout=30) as http:
            while True:
                try:
                    await self.upload_once(http)
                except Exception:
                    logger.error("[Windy] Upload failed", extra=self.logger_context, exc_info=True)
                await asyncio.sleep(self.config.windy_upload_interval)

    async def upload_once(self, http: httpx.AsyncClient):
        records = await asyncio.to_thread(
            self.influx_client.get_recent_weather,
            self.config.windy_source_station,
            SUMMARY_WINDOW,
        )
        params = build_params(self.config.windy_station_id, records, datetime.now(timezone.utc))
        if params is None:
            logger.info("[Windy] No recent readings, so skipping the upload", extra=self.logger_context)
            return

        response = await http.get(
            WINDY_UPDATE_URL,
            params=params,
            headers={"Authorization": f"Bearer {self.config.windy_station_password}"},
        )
        if response.is_success:
            logger.debug("[Windy] Uploaded observation", extra={**self.logger_context, "params": params})
        else:
            logger.warning(
                "[Windy] Upload refused",
                extra={**self.logger_context, "status_code": response.status_code, "body": response.text[:500]},
            )
