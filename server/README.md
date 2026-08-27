# Weather Server

Receives readings from one or more weather stations, stores them in InfluxDB and
draws them in Grafana.

The server has no sensor hardware and no Raspberry Pi dependency. It runs
anywhere that runs Docker: another Raspberry Pi, a NAS, a virtual machine or a
laptop.

## Features

- FastAPI REST API for ingestion.
- InfluxDB time series storage.
- Provisioned Grafana dashboards.
- API key authentication.
- Health and freshness endpoints.
- Accepts readings from several stations.

## Installation

### Docker, recommended

```bash
cd server
cp .env.example .env
# Set API_KEY, INFLUXDB_TOKEN, INFLUXDB_ADMIN_PASSWORD and GRAFANA_ADMIN_PASSWORD.
docker compose up -d
```

That starts InfluxDB on port 8086, Grafana on port 3000 and the API on port
8080.

Set every value in `.env` before you start the stack. The compose file falls
back to placeholder credentials, which are fine for a first local run and unsafe
for anything reachable.

### Local development

```bash
cd server
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

uv venv
source .venv/bin/activate
uv pip install -e .
uv run weather-server --port 8080
```

## Configuration

```bash
SERVER_HOST=0.0.0.0
SERVER_PORT=8080
INFLUXDB_URL=http://localhost:8086
INFLUXDB_TOKEN=<token>
INFLUXDB_ORG=weather
INFLUXDB_BUCKET=weather_data
API_KEY=<the key the client sends>
CORS_ALLOW_ORIGINS=
MAX_TIMESTAMP_FUTURE_SECONDS=3600
MAX_TIMESTAMP_AGE_DAYS=30
LOG_LEVEL=INFO
```

`CORS_ALLOW_ORIGINS` is empty by default, which keeps CORS off. A collector
talks server to server and does not need it. Set a comma separated origin list
only if a browser client needs access.

The two timestamp limits bound what the server accepts. A collector without a
real time clock can report a wrong time after a power cut, and these limits stop
that data from reaching the database. A reading outside the window is dropped and
counted, but the request still succeeds, because refusing the batch would keep it
buffered on the client for ever.

## API

All ingestion endpoints need `Authorization: Bearer <API_KEY>`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | API and InfluxDB status |
| `POST` | `/api/v1/weather/batch` | Ingest a batch of readings |
| `POST` | `/api/v1/health/system` | Ingest client health |
| `GET` | `/api/v1/stations` | List reporting stations |
| `GET` | `/api/v1/stats` | Counts for the last 24 hours |

Batch bodies of ten readings or more arrive gzipped. The server decompresses
them in `GzipRequestMiddleware`.

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
  "batch_id": "<uuid>"
}
```

## Grafana

Docker Compose provisions the data source and both dashboards from
`grafana/provisioning`. Change a dashboard in this repository rather than in the
Grafana interface, because the provider overwrites interface edits on restart.

- **Weather Conditions**: current values, with temperature, humidity, pressure
  and wind history.
- **Station Health**: buffer depth, CPU, memory, disk and chip temperature.

Both dashboards show an outage as a break in the line rather than a straight
line across it. Every query uses `aggregateWindow` with `createEmpty: true`, and
every graph sets `spanNulls: false`.

## Dependencies

- `fastapi` for the API.
- `uvicorn` for the server.
- `influxdb-client` for storage.

## Architecture

```
Server
├── FastAPI
│   ├── Authentication
│   ├── Validation
│   └── Gzip handling
├── InfluxDB
│   └── Time series storage
└── Grafana
    └── Provisioned dashboards
```
