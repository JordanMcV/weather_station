# Weather Client (Pi Zero)

Lightweight weather data collector for Raspberry Pi Zero with WeatherHAT sensor.

## Features

- 🌡️ WeatherHAT sensor reading (temperature, humidity, pressure, wind, rain)
- 💾 Local SQLite buffering for network resilience
- 📤 Batch HTTP uploads with retry logic
- 🔄 Exponential backoff for failed uploads
- 📊 System health monitoring
- ⚡ Optimized for low-power Pi Zero

## Installation

### Local Development

```bash
cd client
poetry install
```

### Docker Deployment

```bash
cd client
docker-compose up -d
```

## Configuration

Create a `.env` file (see `.env.example`):

```bash
SERVER_URL=http://pi5:8080
API_KEY=your-api-key-here
STATION_ID=piw
UPLOAD_INTERVAL=300
SENSOR_READ_INTERVAL=15.0
DATABASE_PATH=/data/weather.db
LOG_LEVEL=INFO
```

## Usage

### Run directly

```bash
poetry run weather-client
```

### Run with custom settings

```bash
poetry run weather-client \
  --server-url http://pi5:8080 \
  --api-key your-key \
  --station-id piw \
  --upload-interval 300
```

### Check status

```bash
poetry run weather-client --status
```

### Run as module

```bash
poetry run python -m weather_client
```

## Docker Deployment

The client requires access to I2C/SPI devices for WeatherHAT:

```yaml
devices:
  - /dev/i2c-1:/dev/i2c-1
  - /dev/spidev0.0:/dev/spidev0.0
  - /dev/gpiomem:/dev/gpiomem
```

## Dependencies

- **weatherhat**: WeatherHAT sensor library
- **httpx**: Async HTTP client for data uploads
- **psutil**: System health monitoring

No FastAPI, no InfluxDB - minimal and efficient!

## Architecture

```
Client (Pi Zero)
├── Sensor Reading (15s interval)
│   └── WeatherHAT I2C/SPI
├── Local Buffer (SQLite)
│   └── Up to 1000 readings
└── Upload Service (5min interval)
    └── HTTP POST to server
```
