# Weather Station Monorepo

Dual Raspberry Pi weather monitoring system with separated client and server codebases.

## 🏗️ Architecture

This is a **monorepo** with two fully independent packages:

- **`client/`** - Lightweight Pi Zero W collector (WeatherHAT sensor), on bare metal
- **`server/`** - API + InfluxDB + Grafana on pi4, in Docker Compose

### Why Monorepo?

- ✅ **Complete separation** - No shared code or dependencies
- ✅ **Optimized builds** - Client is minimal (no FastAPI/InfluxDB), Server has no WeatherHAT
- ✅ **Independent deployment** - The client runs on bare metal, the server runs in Docker
- ✅ **Clear boundaries** - Models are intentionally duplicated to prevent coupling

## 📦 Packages

### Client (Pi Zero W)
```bash
cd client/
# Install with uv (blazing fast!)
uv venv && source .venv/bin/activate
uv pip install -e .
uv run weather-client
```

**Dependencies:** weatherhat, st7789, pillow, httpx, psutil
**Package Manager:** [uv](https://github.com/astral-sh/uv) (extremely fast, perfect for Pi Zero)
**Deployment:** Bare metal with a systemd unit. There is no client Dockerfile.
**Purpose:** Collect sensor data, buffer locally, upload to server

[📖 Client README](./client/README.md)

### Server (pi4)
```bash
cd server/
docker compose up -d
```

**Dependencies:** fastapi, uvicorn, influxdb-client
**Package Manager:** [uv](https://github.com/astral-sh/uv)
**Purpose:** Ingest data via REST API, store in InfluxDB, visualize with Grafana

[📖 Server README](./server/README.md)

## 🚀 Quick Start

### 1. Set up Server (pi4)

```bash
cd server
cp .env.example .env
# Edit .env with your credentials

# Start InfluxDB + Grafana + API
docker compose up -d

# Check health
curl http://localhost:8080/api/v1/health
```

### 2. Set up Client (Pi Zero W)

```bash
cd client
cp .env.example .env
# Edit .env with server URL and API key

# Run the collector directly
uv run weather-client

# Install as a service for production
sudo cp weather-client.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now weather-client
```

## 📊 Accessing Services

- **Weather API:** http://pi4:8080
- **Grafana:** http://pi4:3000 (admin/password from .env)
- **InfluxDB:** http://pi4:8086

## 🏛️ Project Structure

```
weather_station/
├── client/              # Pi Zero W collector, bare metal
│   ├── src/weather_client/
│   ├── pyproject.toml   # Minimal deps
│   └── weather-client.service
│
├── server/              # pi4 server, Docker
│   ├── src/weather_server/
│   ├── pyproject.toml   # Server deps
│   ├── Dockerfile
│   └── docker-compose.yaml
│
├── .env.example         # Root config template
├── CLAUDE.md           # Architecture docs
└── README.md           # This file
```

## 🔧 Development

### Client Development
```bash
cd client
uv venv && source .venv/bin/activate
uv pip install -e .
uv run weather-client --status

# Log readings without buffering or uploading
uv run weather-client --dry-run

# Choose which optional sensors to read
uv run weather-client --enabled-sensors wind
```

Set `ENABLED_SENSORS` to pick the optional sensors. Choose from `wind` and
`rain`. Temperature, humidity and pressure come from the BME280 and are always
read. The rain gauge is disabled by default, because it does not register water.

### Server Development
```bash
cd server
uv venv && source .venv/bin/activate
uv pip install -e .
uv run weather-server --port 8080
```

## 🐳 Deployment

### Client (Pi Zero W)

The client runs on bare metal, because Docker wastes memory on a Pi Zero. It
needs I2C and SPI access for the WeatherHAT. Deploy it with the systemd unit in
`client/weather-client.service`.

### Server (pi4)
```bash
cd server
docker compose up -d
```

Starts the complete stack: InfluxDB, Grafana, Weather API.

## 📝 Configuration

Each package has its own `.env.example` file:

- `client/.env.example` - Client-specific settings
- `server/.env.example` - Server-specific settings
- `.env.example` - Root template showing all options

## 🌐 Data Flow

```
Pi Zero W (Client)        →      pi4 (Server)
┌──────────────┐                ┌──────────────┐
│ WeatherHAT   │                │ FastAPI      │
│ Sensor       │                │ REST API     │
└──────┬───────┘                └──────┬───────┘
       │                               │
       ▼                               ▼
┌──────────────┐                ┌──────────────┐
│ SQLite       │    HTTP POST   │ InfluxDB     │
│ Buffer       │ ──────────────▶│ Time Series  │
└──────────────┘                └──────┬───────┘
                                       │
                                       ▼
                                ┌──────────────┐
                                │ Grafana      │
                                │ Dashboards   │
                                └──────────────┘
```

## 📚 Documentation

- [CLAUDE.md](./CLAUDE.md) - Complete architecture documentation
- [client/README.md](./client/README.md) - Client package details
- [server/README.md](./server/README.md) - Server package details

## 🎯 Design Philosophy

1. **No shared code** - Models are duplicated intentionally
2. **Separate dependencies** - Client stays lightweight, server full-featured
3. **Independent deployment** - Each can be deployed/updated separately
4. **Clear contracts** - HTTP REST API is the only interface