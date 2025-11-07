# Weather Station Architecture

## Project Overview
Dual Raspberry Pi weather station system with weatherhat sensor hardware, InfluxDB storage, and Grafana visualization.

**MONOREPO STRUCTURE**: This project is organized as a monorepo with completely separated client and server codebases:
- `client/` - Lightweight Pi Zero collector (minimal dependencies)
- `server/` - Full-featured Pi 5 API server (InfluxDB, FastAPI, Grafana)

## Hardware Setup
- **Pi W (piw)**: Weather station collector - underpowered, slow network, weatherhat hardware
- **Pi 5**: Analytics server - powerful, fast network, InfluxDB + Grafana

## Recommended Architecture

### Pi W (Collector Mode) - Lightweight Data Collection
```
┌─────────────────────────────────────┐
│              Pi W (piw)             │
├─────────────────────────────────────┤
│ • WeatherHat sensor reading         │
│ • Local SQLite buffering            │
│ • Batch HTTP uploads                │
│ • Retry logic + error handling      │
│ • Health monitoring                 │
└─────────────────────────────────────┘
```

**Components:**
- **Data Collector**: Read weatherhat every 15-30 seconds
- **Local Buffer**: SQLite database for reliability during network outages
- **Upload Service**: Batch upload every 5 minutes (configurable)
- **Retry Logic**: Exponential backoff for failed uploads
- **Health Monitor**: System status, disk space, network connectivity

### Pi 4 (Server Mode) - Analytics & Storage
```
┌─────────────────────────────────────┐
│              Pi 4                   │
├─────────────────────────────────────┤
│ • HTTP API server                   │
│ • Data validation & processing      │
│ • InfluxDB time series storage      │
│ • Grafana visualization             │
│ • Monitoring & alerting             │
└─────────────────────────────────────┘
```

**Components:**
- **Ingestion API**: REST endpoints to receive weather data
- **Data Pipeline**: Validation, transformation, deduplication
- **InfluxDB**: Time series database with retention policies
- **Grafana**: Real-time dashboards and historical analysis
- **Monitoring**: System health, data freshness alerts

## Data Flow Architecture

```
Pi W (Collector)                    Pi 5 (Server)
┌─────────────┐                    ┌─────────────┐
│ WeatherHat  │                    │             │
│   Sensor    │                    │  HTTP API   │
└──────┬──────┘                    │   Server    │
       │                           └──────┬──────┘
       ▼                                  │
┌─────────────┐    HTTP POST              ▼
│   Local     │   (JSON batch)     ┌─────────────┐
│  SQLite     │ ──────────────────▶│ Data        │
│  Buffer     │                    │ Validation  │
└─────────────┘                    └──────┬──────┘
                                          │
                                          ▼
                                   ┌─────────────┐
                                   │  InfluxDB   │
                                   │ Time Series │
                                   └──────┬──────┘
                                          │
                                          ▼
                                   ┌─────────────┐
                                   │   Grafana   │
                                   │ Dashboards  │
                                   └─────────────┘
```

## Communication Protocol

### HTTP REST API
- **Endpoint**: `POST /api/v1/weather/batch`
- **Authentication**: API key in header
- **Payload**: JSON array of readings
- **Compression**: gzip for bandwidth efficiency
- **Retry**: Exponential backoff (1s, 2s, 4s, 8s, max 60s)

### Data Format
```json
{
  "readings": [
    {
      "timestamp": "2025-09-20T10:00:00Z",
      "temperature": 22.5,
      "humidity": 65.2,
      "pressure": 1013.25,
      "wind_speed": 2.1,
      "wind_direction": 180,
      "rain_total": 0.0
    }
  ],
  "station_id": "piw",
  "batch_id": "uuid"
}
```

## Deployment Configuration

### Pi W (Collector) - Bare Metal
- **Deployment**: Direct on bare metal (no Docker - saves resources!)
- **Package Manager**: uv (ultra-fast Python package installer)
- **Service Management**: systemd for auto-start on boot
- **Upload Interval**: 5 minutes
- **Buffer Size**: 1000 readings max
- **Retry Attempts**: 5 with exponential backoff
- **Local Storage**: SQLite in `/data/weather.db`
- **Resource Optimization**: Minimal dependencies, no containerization overhead

### Pi 5 (Server) - Docker Compose
- **Deployment**: Docker Compose stack
- **Components**: InfluxDB + Grafana + FastAPI server
- **Data Retention**: 1 year raw data, 5 years aggregated
- **Monitoring**: Prometheus + Alertmanager (optional)

## Reliability Features

### Network Resilience
- Local SQLite buffering on Pi W
- Automatic retry with exponential backoff
- Graceful degradation during outages
- Data deduplication on server side

### Data Integrity
- Checksum validation
- Timestamp validation
- Sensor range validation
- Duplicate detection

### Monitoring
- Health check endpoints
- Data freshness alerts
- Disk space monitoring
- Network connectivity status

## Monorepo Structure

```
weather_station/
├── client/                    # Pi Zero collector package (BARE METAL)
│   ├── src/weather_client/
│   │   ├── collector/        # Sensor reading & buffering
│   │   ├── config.py         # Client-only configuration
│   │   ├── models.py         # Data models (duplicated)
│   │   └── main.py           # Entry point
│   ├── pyproject.toml        # Minimal dependencies (weatherhat, httpx, psutil)
│   ├── weather-client.service # systemd service file for auto-start
│   ├── .env.example          # Environment configuration
│   └── README.md             # Bare metal installation guide
│
├── server/                    # Pi 5 server package (DOCKER)
│   ├── src/weather_server/
│   │   ├── api/              # FastAPI routes & InfluxDB client
│   │   ├── config.py         # Server-only configuration
│   │   ├── models.py         # Data models (duplicated)
│   │   └── main.py           # Entry point
│   ├── pyproject.toml        # Server dependencies (fastapi, uvicorn, influxdb-client)
│   ├── Dockerfile            # Uses uv
│   ├── docker-compose.yaml   # Includes InfluxDB + Grafana
│   ├── .env.example
│   └── README.md
│
├── .env.example              # Root environment template
├── pyproject.toml            # Root monorepo metadata
└── CLAUDE.md                 # This file
```

## Development Commands

### Client (Pi W) Setup - Bare Metal with uv
```bash
cd client

# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$PATH"

# Create venv and install dependencies (blazing fast!)
uv venv
source .venv/bin/activate
uv pip install -e .

# Run collector (development)
uv run weather-client --server-url http://pi5:8080 --api-key your-key

# Check buffer status
uv run weather-client --status

# Setup as systemd service (production)
sudo cp weather-client.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable weather-client
sudo systemctl start weather-client
sudo systemctl status weather-client
```

### Server (Pi 5) Setup
```bash
cd server

# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$PATH"

# Install dependencies (for local development)
uv venv
source .venv/bin/activate
uv pip install -e .

# Start full stack (InfluxDB + Grafana + API)
docker-compose up -d

# Or run API server directly (local development)
uv run weather-server --port 8080

# Check data ingestion
curl http://localhost:8080/api/v1/health
```

## Configuration Files

### Client Environment Variables (client/.env)
- `SERVER_URL`: Pi 5 API endpoint
- `API_KEY`: Authentication key
- `STATION_ID`: Station identifier
- `UPLOAD_INTERVAL`: Seconds between uploads
- `SENSOR_READ_INTERVAL`: Sensor polling interval
- `DATABASE_PATH`: SQLite buffer path
- `TEMPERATURE_OFFSET`: Sensor calibration

### Server Environment Variables (server/.env)
- `SERVER_HOST`: API bind host
- `SERVER_PORT`: API bind port
- `INFLUXDB_URL`: InfluxDB connection string
- `INFLUXDB_TOKEN`: InfluxDB authentication token
- `INFLUXDB_ORG`: InfluxDB organization
- `INFLUXDB_BUCKET`: InfluxDB bucket name
- `API_KEY`: Client authentication key

### Grafana Dashboards
- Real-time weather conditions
- Historical trends (daily/weekly/monthly)
- System health monitoring
- Data quality metrics

## Future Enhancements
- MQTT support for real-time streaming
- Machine learning weather predictions
- Mobile app integration
- Multiple sensor station support
- Weather alerts and notifications
