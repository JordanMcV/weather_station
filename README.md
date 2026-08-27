# Weather Station

A two-part weather monitoring system. A Raspberry Pi Zero reads a Pimoroni
WeatherHAT and uploads readings over HTTP. A server stores them in InfluxDB and
draws them in Grafana.

## Architecture

The repository holds two independent packages:

- `client/` reads the sensor and runs on a Raspberry Pi Zero, on bare metal.
- `server/` receives the readings and runs anywhere that runs Docker.

The packages share no code. The HTTP API is the only interface between them, and
the data models are duplicated on purpose so that neither side constrains the
other.

The client needs a Raspberry Pi Zero because the WeatherHAT is a Pi HAT and the
library talks to it over I2C and SPI. The server has no such constraint. It runs
on another Raspberry Pi, a NAS, a virtual machine or a laptop.

## Data flow

```
Raspberry Pi Zero                Server
┌──────────────┐                ┌──────────────┐
│ WeatherHAT   │                │ FastAPI      │
│ sensor       │                │ REST API     │
└──────┬───────┘                └──────┬───────┘
       │                               │
       ▼                               ▼
┌──────────────┐    HTTP POST   ┌──────────────┐
│ SQLite       │ ──────────────▶│ InfluxDB     │
│ buffer       │                │ time series  │
└──────────────┘                └──────┬───────┘
                                       │
                                       ▼
                                ┌──────────────┐
                                │ Grafana      │
                                │ dashboards   │
                                └──────────────┘
```

The client writes every reading to a local SQLite buffer first, then uploads in
batches. The buffer holds 72 hours of readings, so a network outage costs
nothing as long as it ends within three days.

## Quick start

### 1. Start the server

```bash
cd server
cp .env.example .env
# Set API_KEY, INFLUXDB_TOKEN and the two passwords in .env.
docker compose up -d
curl http://localhost:8080/api/v1/health
```

### 2. Set up the client

```bash
cd client
cp .env.example .env
# Set SERVER_URL and the same API_KEY you gave the server.
uv venv && source .venv/bin/activate
uv pip install -e .
uv run weather-client
```

### 3. Install the client as a service

```bash
sudo cp weather-client.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now weather-client
```

## Services

Replace `<server-host>` with the address of the machine running the server.

| Service | Address |
| --- | --- |
| Weather API | `http://<server-host>:8080` |
| Grafana | `http://<server-host>:3000` |
| InfluxDB | `http://<server-host>:8086` |

Sign in to Grafana with the credentials from `server/.env`.

## Project structure

```
weather_station/
├── client/                    # Pi Zero collector, bare metal
│   ├── src/weather_client/
│   ├── pyproject.toml
│   └── weather-client.service
│
├── server/                    # API, InfluxDB and Grafana, in Docker
│   ├── src/weather_server/
│   ├── grafana/provisioning/
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── docker-compose.yaml
│
├── .env.example
└── CLAUDE.md                  # Architecture notes
```

## Development

### Client

```bash
cd client
uv venv && source .venv/bin/activate
uv pip install -e .

uv run weather-client --status      # Show buffer state
uv run weather-client --dry-run     # Log readings without buffering or uploading
```

Temperature, humidity and pressure come from the BME280 and always read. Set
`ENABLED_SENSORS` to add the optional sensors, choosing from `wind` and `rain`.

### Server

```bash
cd server
uv venv && source .venv/bin/activate
uv pip install -e .
uv run weather-server --port 8080
```

## Design decisions

The client and server duplicate their data models rather than share them. The
duplication keeps the client dependencies small, which matters on a Pi Zero, and
it stops a change on one side from forcing a change on the other.

The client runs on bare metal rather than in Docker. A Pi Zero has little memory
and the container runtime earns nothing here.

The client stamps each reading when it reads the sensor and never restamps it at
upload time. InfluxDB overwrites a point that repeats the same timestamp, so a
batch that uploads twice cannot create duplicates.

## Documentation

- [client/README.md](./client/README.md) for the collector.
- [server/README.md](./server/README.md) for the API and the stack.
- [CLAUDE.md](./CLAUDE.md) for the full architecture notes.
