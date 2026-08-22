"""FastAPI application for weather data ingestion."""

import gzip
import logging
import zlib
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..config import Config
from ..models import WeatherBatch, SystemHealth
from .influx_client import InfluxDBClient


logger = logging.getLogger(__name__)
security = HTTPBearer()


class GzipRequestMiddleware:
    """Decompress request bodies that arrive with Content-Encoding: gzip.

    The collector compresses larger batches to save bandwidth on a slow link.
    Starlette does not decompress request bodies, so do it here.

    A body that is not valid gzip passes through unchanged. Collectors before
    version 0.2 set the header without compressing the body, so rejecting it
    would refuse every batch from a station that has not been updated yet.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        encoding = Headers(scope=scope).get("content-encoding", "").lower()
        if "gzip" not in encoding:
            await self.app(scope, receive, send)
            return

        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                break
            body.extend(message.get("body", b""))
            more_body = message.get("more_body", False)

        raw = bytes(body)
        try:
            payload = gzip.decompress(raw)
        except (OSError, EOFError, zlib.error):
            payload = raw
            logger.warning(
                "[Weather API] Request claimed gzip but the body is not gzip, so reading it as plain text",
                extra={"content_length": len(raw), "path": scope.get("path")},
            )

        headers = [
            (name, value)
            for name, value in scope["headers"]
            if name.lower() not in (b"content-encoding", b"content-length")
        ]
        headers.append((b"content-length", str(len(payload)).encode("latin-1")))
        scope = dict(scope, headers=headers)

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": payload, "more_body": False}

        await self.app(scope, replay, send)


def as_utc(moment: datetime) -> datetime:
    """Treat a naive timestamp as UTC, so old and new collectors compare alike."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def partition_readings(batch: WeatherBatch, config: Config) -> Tuple[List, List[str]]:
    """Split a batch into readings worth storing and reasons for the rest.

    Rejecting the whole batch would be worse than dropping a bad reading. The
    collector treats 400 as permanent, so it would keep the batch buffered for
    ever and the buffer would grow without limit.
    """
    now = datetime.now(timezone.utc)
    latest = now + timedelta(seconds=config.max_timestamp_future_seconds)
    earliest = now - timedelta(days=config.max_timestamp_age_days)

    accepted = []
    rejections = []

    for reading in batch.readings:
        if not reading.validate():
            rejections.append("sensor value out of range")
            continue

        moment = as_utc(reading.timestamp)
        if moment > latest:
            rejections.append(f"timestamp {moment.isoformat()} is too far in the future")
            continue
        if moment < earliest:
            rejections.append(f"timestamp {moment.isoformat()} is too old")
            continue

        accepted.append(reading)

    return accepted, rejections


def create_app(config: Config) -> FastAPI:
    app = FastAPI(
        title="Weather Station API",
        description="Weather data ingestion API for dual-Pi weather station",
        version="0.1.0"
    )

    # Decompress gzip request bodies before routing
    app.add_middleware(GzipRequestMiddleware)

    # Only expose CORS when a browser origin is configured. Credentialed
    # requests need explicit origins, so never pair them with a wildcard.
    if config.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_allow_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Content-Encoding"],
        )

    # Initialize InfluxDB client
    influx_client = InfluxDBClient(config)

    async def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
        """Verify API key authentication."""
        if credentials.credentials != config.api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return credentials.credentials

    @app.get("/")
    async def root():
        """Root endpoint."""
        return {"message": "Weather Station API", "version": "0.1.0"}

    @app.get("/api/v1/health")
    async def health_check():
        """Health check endpoint."""
        try:
            # Test InfluxDB connection
            influx_healthy = await influx_client.test_connection()

            return {
                "status": "healthy" if influx_healthy else "degraded",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "services": {
                    "influxdb": "healthy" if influx_healthy else "unhealthy",
                    "api": "healthy"
                }
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e)
            }

    @app.post("/api/v1/weather/batch")
    async def ingest_weather_batch(
        batch_data: dict,
        api_key: str = Depends(verify_api_key)
    ):
        """Ingest a batch of weather readings."""
        try:
            batch = WeatherBatch.from_dict(batch_data)

            if not batch.readings or not batch.station_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Batch must name a station and carry at least one reading"
                )

            accepted, rejections = partition_readings(batch, config)

            if rejections:
                logger.warning(
                    "[Weather API] Discarded readings that failed validation",
                    extra={
                        "batch_id": batch.batch_id,
                        "station_id": batch.station_id,
                        "rejected_count": len(rejections),
                        "first_reasons": rejections[:5],
                    },
                )

            if accepted:
                stored = WeatherBatch(
                    readings=accepted,
                    station_id=batch.station_id,
                    batch_id=batch.batch_id,
                )
                if not await influx_client.write_batch(stored):
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to store weather data"
                    )

            logger.info(f"Successfully ingested batch {batch.batch_id} with {len(accepted)} readings from {batch.station_id}")

            return {
                "status": "success",
                "batch_id": batch.batch_id,
                "readings_count": len(accepted),
                "rejected_count": len(rejections),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        except HTTPException:
            # Already a deliberate status code, so do not mask it as a 500.
            raise
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid data format: {str(e)}"
            )
        except Exception:
            logger.error("[Weather API] Error ingesting weather batch", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error"
            )

    @app.post("/api/v1/health/system")
    async def ingest_system_health(
        health_data: dict,
        api_key: str = Depends(verify_api_key)
    ):
        """Ingest system health metrics."""
        try:
            # Parse health data
            health = SystemHealth(
                timestamp=datetime.fromisoformat(health_data["timestamp"].replace("Z", "+00:00")),
                station_id=health_data["station_id"],
                cpu_percent=health_data["cpu_percent"],
                memory_percent=health_data["memory_percent"],
                disk_percent=health_data["disk_percent"],
                temperature=health_data.get("temperature"),
                network_connected=health_data.get("network_connected", True),
                last_upload=datetime.fromisoformat(health_data["last_upload"].replace("Z", "+00:00")) if health_data.get("last_upload") else None,
                buffer_size=health_data.get("buffer_size", 0),
            )

            # Store in InfluxDB
            success = await influx_client.write_health(health)

            if not success:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to store health data"
                )

            logger.debug(f"Successfully ingested health data from {health.station_id}")

            return {
                "status": "success",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        except HTTPException:
            # Already a deliberate status code, so do not mask it as a 500.
            raise
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid data format: {str(e)}"
            )
        except Exception:
            logger.error("[Weather API] Error ingesting health data", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error"
            )

    @app.get("/api/v1/stations")
    async def list_stations():
        """List all weather stations."""
        try:
            stations = await influx_client.get_stations()
            return {"stations": stations}
        except Exception as e:
            logger.error(f"Error listing stations: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to list stations"
            )

    @app.get("/api/v1/stats")
    async def get_stats():
        """Get API statistics."""
        try:
            stats = await influx_client.get_stats()
            return stats
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get statistics"
            )

    return app
