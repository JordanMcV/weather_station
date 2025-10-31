# Weather Station Monorepo

Dual Raspberry Pi weather monitoring system with separated client and server codebases.

## 🏗️ Architecture

This is a **monorepo** with two fully independent packages:

- **`client/`** - Lightweight Pi Zero collector (WeatherHAT sensor)
- **`server/`** - Full-featured Pi 5 API + InfluxDB + Grafana

### Why Monorepo?

- ✅ **Complete separation** - No shared code or dependencies
- ✅ **Optimized builds** - Client is minimal (no FastAPI/InfluxDB), Server has no WeatherHAT
- ✅ **Independent deployment** - Each package has its own Docker setup
- ✅ **Clear boundaries** - Models are intentionally duplicated to prevent coupling

## 📦 Packages

### Client (Pi Zero)
```bash
cd client/
poetry install
poetry run weather-client
```

**Dependencies:** weatherhat, httpx, psutil
**Size:** Minimal - optimized for Pi Zero
**Purpose:** Collect sensor data, buffer locally, upload to server

[📖 Client README](./client/README.md)

### Server (Pi 5)
```bash
cd server/
docker-compose up -d
```

**Dependencies:** fastapi, uvicorn, influxdb-client
**Size:** Full-featured
**Purpose:** Ingest data via REST API, store in InfluxDB, visualize with Grafana

[📖 Server README](./server/README.md)

## 🚀 Quick Start

### 1. Set up Server (Pi 5)

```bash
cd server
cp .env.example .env
# Edit .env with your credentials

# Start InfluxDB + Grafana + API
docker-compose up -d

# Check health
curl http://localhost:8080/api/v1/health
```

### 2. Set up Client (Pi Zero)

```bash
cd client
cp .env.example .env
# Edit .env with server URL and API key

# Run collector
docker-compose up -d

# Or run directly
poetry run weather-client
```

## 📊 Accessing Services

- **Weather API:** http://localhost:8080
- **Grafana:** http://localhost:3000 (admin/password from .env)
- **InfluxDB:** http://localhost:8086

## 🏛️ Project Structure

```
weather_station/
├── client/              # Pi Zero collector
│   ├── src/weather_client/
│   ├── pyproject.toml   # Minimal deps
│   ├── Dockerfile
│   └── docker-compose.yaml
│
├── server/              # Pi 5 server
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
poetry install
poetry run weather-client --status
```

### Server Development
```bash
cd server
poetry install
poetry run weather-server --port 8080
```

## 🐳 Docker Deployment

### Client (Pi Zero)
```bash
cd client
docker-compose up -d
```

Requires I2C/SPI device access for WeatherHAT.

### Server (Pi 5)
```bash
cd server
docker-compose up -d
```

Starts complete stack: InfluxDB, Grafana, Weather API.

## 📝 Configuration

Each package has its own `.env.example` file:

- `client/.env.example` - Client-specific settings
- `server/.env.example` - Server-specific settings
- `.env.example` - Root template showing all options

## 🌐 Data Flow

```
Pi Zero (Client)          →      Pi 5 (Server)
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