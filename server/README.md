# Weather Server (Pi 5)

High-performance weather data ingestion API and analytics server for Raspberry Pi 5.

## Features

- 🚀 FastAPI REST API for data ingestion
- 📊 InfluxDB time series storage
- 📈 Grafana visualization (via docker-compose)
- 🔐 API key authentication
- ✅ Health monitoring
- 📡 Multi-station support

## Installation

### Local Development

```bash
cd server
poetry install
```

### Docker Deployment (Recommended)

```bash
cd server
docker-compose up -d
```

This starts:
- InfluxDB on port 8086
- Grafana on port 3000
- Weather API on port 8080

## Configuration

Create a `.env` file (see `.env.example`):

```bash
SERVER_HOST=0.0.0.0
SERVER_PORT=8080
INFLUXDB_URL=http://localhost:8086
INFLUXDB_TOKEN=your-influxdb-token
INFLUXDB_ORG=weather
INFLUXDB_BUCKET=weather_data
API_KEY=your-api-key-here
LOG_LEVEL=INFO
```

## Usage

### Run directly

```bash
poetry run weather-server
```

### Run with custom settings

```bash
poetry run weather-server \
  --host 0.0.0.0 \
  --port 8080 \
  --influxdb-url http://localhost:8086
```

### Run as module

```bash
poetry run python -m weather_server
```

## API Endpoints

### Health Check
```bash
GET /api/v1/health
```

### Ingest Weather Batch
```bash
POST /api/v1/weather/batch
Authorization: Bearer your-api-key-here
Content-Type: application/json

{
  "readings": [...],
  "station_id": "piw",
  "batch_id": "uuid"
}
```

### System Health
```bash
POST /api/v1/health/system
Authorization: Bearer your-api-key-here
```

### List Stations
```bash
GET /api/v1/stations
```

### Get Statistics
```bash
GET /api/v1/stats
```

## Dependencies

- **fastapi**: Modern web framework
- **uvicorn**: ASGI server
- **influxdb-client**: Time series database client

No WeatherHAT dependency - server only!

## Architecture

```
Server (Pi 5)
├── FastAPI API Server
│   ├── Authentication
│   ├── Validation
│   └── Data Processing
├── InfluxDB
│   ├── Time Series Storage
│   └── Query Engine
└── Grafana
    └── Dashboards
```

## Grafana Setup

1. Access Grafana at http://localhost:3000
2. Login with credentials from `.env`
3. Add InfluxDB data source
4. Import weather dashboards

## Monitoring

Health check endpoint returns:
- API status
- InfluxDB connection status
- 24h data statistics
