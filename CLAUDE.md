# Weather Station Architecture

## Project Overview
Dual Raspberry Pi weather station system with weatherhat sensor hardware, InfluxDB storage, and Grafana visualization.

**MONOREPO STRUCTURE**: This project is organized as a monorepo with completely separated client and server codebases:
- `client/` - Lightweight Pi Zero collector (minimal dependencies)
- `server/` - Full-featured API server (InfluxDB, FastAPI, Grafana)

## Hardware Setup
- **Collector**: a Raspberry Pi Zero with WeatherHAT hardware. The Pi Zero is a
  requirement, because the WeatherHAT is a Pi HAT read over I2C and SPI. It is
  underpowered and its wifi is often weak, since it sits outdoors.
- **Server**: InfluxDB, Grafana and FastAPI in Docker Compose. It needs no
  sensor hardware and runs on any machine that runs Docker.

The collector and the server may share a host with other services, so treat
ports 80 and 443 as possibly taken.

## Recommended Architecture

### Collector Mode - Lightweight Data Collection
```
┌─────────────────────────────────────┐
│             Collector               │
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

### Server Mode - Analytics & Storage
```
┌─────────────────────────────────────┐
│              Server                 │
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
Collector                           Server
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
- **Compression**: gzip request bodies for batches of 10 readings or more. The server decompresses them in `GzipRequestMiddleware`.
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
  "station_id": "<station>",
  "batch_id": "uuid"
}
```

## Deployment Configuration

### Collector - Bare Metal
- **Deployment**: Direct on bare metal (no Docker - saves resources!)
- **Package Manager**: uv (ultra-fast Python package installer)
- **Service Management**: systemd for auto-start on boot
- **Upload Interval**: 5 minutes
- **Buffer Size**: 17280 readings, which is 72 hours at the 15 second read interval
- **Retry Attempts**: 5 with exponential backoff
- **Local Storage**: SQLite in `/var/lib/weather-client/weather.db`. The path must persist across a reboot, so do not put it in `/tmp`.
- **Resource Optimization**: Minimal dependencies, no containerization overhead

### Server - Docker Compose
- **Deployment**: Docker Compose stack
- **Components**: InfluxDB + Grafana + FastAPI server
- **Data Retention**: 1 year raw data, 5 years aggregated
- **Monitoring**: Prometheus + Alertmanager (optional)

## Reliability Features

### Network Resilience
- Local SQLite buffering on the collector, trimmed to `BUFFER_MAX_SIZE`
- Automatic retry with exponential backoff
- Uploads split into chunks of `UPLOAD_BATCH_SIZE`, so a long backlog still fits
  inside the HTTP timeout
- Graceful degradation during outages

### Data Integrity
- Sensor range validation, see `WeatherReading.validate`
- Timestamp validation against `MAX_TIMESTAMP_FUTURE_SECONDS` and
  `MAX_TIMESTAMP_AGE_DAYS`
- A reading that fails either check is dropped and counted. The request still
  succeeds, because refusing the batch would keep it buffered for ever.

Deduplication needs no code. InfluxDB overwrites a point that repeats the same
measurement, tag set, field key and timestamp. The collector stores the
timestamp with the reading and never regenerates it, so a batch that uploads
twice cannot create duplicates. Preserve that property: do not stamp readings at
upload time.

A Raspberry Pi has no battery backed clock, so after a power cut it runs on a restored
clock until NTP corrects it. A reading taken in that window is stored as
provisional, with the `CLOCK_BOOTTIME` value that produced it, and it stays out
of uploads. Once the clock is set, `correct_provisional` recovers the true
timestamp from the monotonic interval. Readings from an earlier boot have no
monotonic reference, so they inherit the offset measured on this boot, but only
when their timestamps run contiguously into it.

That rewrite happens before the reading is ever uploaded, so the deduplication
property above still holds. A timestamp never changes once it has been sent.

Checksums need no code either. Compressed batches carry a CRC32 inside the gzip
container, and the server rejects a body that fails to decompress into valid
JSON. Add a second checksum only if corrupt bodies start appearing in the log.

### Monitoring
- Health check endpoints
- Client health reporting to `/api/v1/health/system`
- Disk space and network status in the health payload
- Data freshness is visible on both Grafana dashboards. Alerting that sends a
  notification is not set up yet.

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
├── server/                    # Server package (DOCKER)
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

### Client Setup - Bare Metal with uv
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
uv run weather-client --server-url http://<server-host>:8080 --api-key your-key

# Check buffer status
uv run weather-client --status

# Setup as systemd service (production)
sudo cp weather-client.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable weather-client
sudo systemctl start weather-client
sudo systemctl status weather-client
```

### Server Setup
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
- `SERVER_URL`: API endpoint of the server
- `API_KEY`: Authentication key
- `STATION_ID`: Station identifier
- `UPLOAD_INTERVAL`: Seconds between uploads
- `UPLOAD_BATCH_SIZE`: Readings per request when draining a backlog
- `SENSOR_READ_INTERVAL`: Sensor polling interval
- `DATABASE_PATH`: SQLite buffer path
- `TEMPERATURE_OFFSET`: Sensor calibration
- `ENABLED_SENSORS`: Optional sensors to read, from `wind` and `rain`. Temperature, humidity and pressure always read.
- `HEALTH_UPLOAD_INTERVAL`: Seconds between health reports
- `DRY_RUN`: Set true to log readings without buffering or uploading

### Server Environment Variables (server/.env)
- `SERVER_HOST`: API bind host
- `SERVER_PORT`: API bind port
- `INFLUXDB_URL`: InfluxDB connection string
- `INFLUXDB_TOKEN`: InfluxDB authentication token
- `INFLUXDB_ORG`: InfluxDB organization
- `INFLUXDB_BUCKET`: InfluxDB bucket name
- `API_KEY`: Client authentication key
- `CORS_ALLOW_ORIGINS`: Comma separated browser origins. Empty keeps CORS off.
- `MAX_TIMESTAMP_FUTURE_SECONDS`: Reject readings stamped further ahead than this
- `MAX_TIMESTAMP_AGE_DAYS`: Reject readings older than this

### Grafana Dashboards

Provisioned from `server/grafana/provisioning`. Change a dashboard in the
repository, not in the Grafana user interface, because the provider overwrites
interface edits.

- **Weather Conditions**: current values, plus temperature, humidity, pressure
  and wind history.
- **Station Health**: buffer depth, CPU, memory, disk and chip temperature from
  the `system_health` measurement.

Both dashboards show an outage as a visible break in the line rather than a
straight line across it. Every query uses `aggregateWindow` with
`createEmpty: true`, and every graph sets `spanNulls: false`. The age panels turn
amber after 15 minutes without data and red after 30.

## Future Enhancements
- MQTT support for real-time streaming
- Machine learning weather predictions
- Mobile app integration
- Multiple sensor station support
- Weather alerts and notifications
