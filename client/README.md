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

### Bare Metal Installation with uv (Optimized for Pi Zero)

```bash
cd client

# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Add uv to PATH (add this to ~/.bashrc for persistence)
export PATH="$HOME/.cargo/bin:$PATH"

# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate

# Install the weather client package
uv pip install -e .
```

**Note**: Running directly on bare metal avoids Docker overhead, saving precious CPU and memory on Pi Zero.

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

### Run the collector

```bash
# With uv (no venv activation needed)
uv run weather-client

# Or after activating venv
source .venv/bin/activate
weather-client
```

### Run with custom settings

```bash
uv run weather-client \
  --server-url http://pi5:8080 \
  --api-key your-key \
  --station-id piw \
  --upload-interval 300
```

### Check status

```bash
uv run weather-client --status
```

### Run as module

```bash
uv run python -m weather_client
```

## Running as a System Service (systemd)

For automatic startup on boot, create a systemd service:

```bash
# Create service file
sudo nano /etc/systemd/system/weather-client.service
```

Add the following content:

```ini
[Unit]
Description=Weather Station Client
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/weather_station/client
Environment="PATH=/home/pi/.cargo/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/pi/.cargo/bin/uv run weather-client
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable weather-client
sudo systemctl start weather-client

# Check status
sudo systemctl status weather-client

# View logs
sudo journalctl -u weather-client -f
```

## Dependencies

- **weatherhat**: WeatherHAT sensor library
- **httpx**: Async HTTP client for data uploads
- **psutil**: System health monitoring

No FastAPI, no InfluxDB - minimal and efficient!

Installed with [uv](https://github.com/astral-sh/uv) for blazing fast installs on Pi Zero.

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
