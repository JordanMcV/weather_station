"""FastAPI application for weather data ingestion."""

import logging
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware

from ..config import Config
from ..models import WeatherBatch, SystemHealth
from .influx_client import InfluxDBClient


logger = logging.getLogger(__name__)
security = HTTPBearer()


def create_app(config: Config) -> FastAPI:
    app = FastAPI(
        title="Weather Station API",
        description="Weather data ingestion API for dual-Pi weather station",
        version="0.1.0"
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
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
                "timestamp": datetime.utcnow().isoformat(),
                "services": {
                    "influxdb": "healthy" if influx_healthy else "unhealthy",
                    "api": "healthy"
                }
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e)
            }

    @app.post("/api/v1/weather/batch")
    async def ingest_weather_batch(
        batch_data: dict,
        api_key: str = Depends(verify_api_key)
    ):
        """Ingest a batch of weather readings."""
        try:
            # Parse and validate the batch
            batch = WeatherBatch.from_dict(batch_data)

            if not batch.validate():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid weather data in batch"
                )

            # Store in InfluxDB
            success = await influx_client.write_batch(batch)

            if not success:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to store weather data"
                )

            logger.info(f"Successfully ingested batch {batch.batch_id} with {len(batch.readings)} readings from {batch.station_id}")

            return {
                "status": "success",
                "batch_id": batch.batch_id,
                "readings_count": len(batch.readings),
                "timestamp": datetime.utcnow().isoformat()
            }

        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid data format: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error ingesting batch: {e}")
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
                "timestamp": datetime.utcnow().isoformat()
            }

        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid data format: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error ingesting health data: {e}")
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
