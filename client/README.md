# Weather Client

Collects readings from a Pimoroni WeatherHAT on a Raspberry Pi Zero and uploads
them to the weather server.

The Pi Zero is a hardware requirement, not a preference. The WeatherHAT is a Pi
HAT, and the library reads it over I2C and SPI.

## Features

- Reads temperature, humidity, pressure, wind and rain from the WeatherHAT.
- Buffers readings in local SQLite, so a network outage costs no data.
- Uploads in batches, with exponential backoff on failure.
- Recovers timestamps taken before NTP sets the clock.
- Reports system health to the server.

## Installation

The client runs on bare metal. Docker costs memory that a Pi Zero cannot spare.

```bash
cd client

# Install uv if you do not have it.
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

uv venv
source .venv/bin/activate
uv pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and set the values:

```bash
SERVER_URL=http://<server-host>:8080
API_KEY=<the key you set on the server>
STATION_ID=<a name for this station>
UPLOAD_INTERVAL=300
SENSOR_READ_INTERVAL=15.0
BUFFER_MAX_SIZE=17280
DATABASE_PATH=/var/lib/weather-client/weather.db
ENABLED_SENSORS=wind
LOG_LEVEL=INFO
```

Put the database somewhere that survives a reboot. Do not put it in `/tmp`,
which systemd empties at boot.

`BUFFER_MAX_SIZE` is a count of readings, not a duration. At the default
15 second interval, 17280 readings hold 72 hours.

Temperature, humidity and pressure always read. `ENABLED_SENSORS` adds the
optional sensors, from `wind` and `rain`.

## Usage

```bash
uv run weather-client                 # Run the collector
uv run weather-client --status        # Show buffer state
uv run weather-client --dry-run       # Log readings without buffering or uploading
```

Override any setting on the command line:

```bash
uv run weather-client \
  --server-url http://<server-host>:8080 \
  --api-key <key> \
  --station-id <name> \
  --upload-interval 300
```

Use `--dry-run` to check the sensor wiring and calibration without writing to
the buffer or reaching the server.

## Run as a service

```bash
sudo cp weather-client.service /etc/systemd/system/
sudo nano /etc/systemd/system/weather-client.service   # Correct the paths
sudo systemctl daemon-reload
sudo systemctl enable --now weather-client
sudo systemctl status weather-client
sudo journalctl -u weather-client -f
```

## WiFi watchdog

The station sits outdoors on a weak link. When the access point restarts,
NetworkManager sometimes stops retrying and the station never reconnects. The
watchdog recovers the link without a trip outside to power cycle the Pi.

A timer runs `wifi-watchdog.sh` every 5 minutes. The script pings the default
gateway. When the ping fails it escalates, one step per check:

| Time down | Action |
|---|---|
| 5, 10 min | Bring the NetworkManager connection up. This clears an autoconnect block. |
| 15, 20 min | Restart NetworkManager. |
| 25, 30 min | Reload the `brcmfmac` driver. This clears a wedged radio. |
| 35 to 55 min | Wait for the access point. Retry the cheap steps every 30 minutes. |
| 60 min | Reboot. |

The wait before each further reboot doubles, up to 6 hours. During one outage
the station reboots after 1 hour, 3 hours, 7 hours and 13 hours, then every 6
hours. A reboot fixes a wedged radio, but it cannot fix an access point that is
still down, so a longer wait each time costs nothing and stops a reboot loop.

The counter lives in `/var/lib/weather-wifi-watchdog/state` and survives a
reboot. It counts checks rather than seconds, because the Pi has no real time
clock and the wall clock is wrong after a reboot that happens while the network
is down. A successful ping clears the counter.

Install it:

```bash
sudo cp weather-wifi-watchdog.service weather-wifi-watchdog.timer /etc/systemd/system/
sudo nano /etc/systemd/system/weather-wifi-watchdog.service   # Correct ExecStart and the interface
sudo systemctl daemon-reload
sudo systemctl enable --now weather-wifi-watchdog.timer
sudo systemctl list-timers weather-wifi-watchdog.timer
```

Check that the connection name matches your installation before you enable it:

```bash
nmcli -g NAME connection show
```

Watch what it does:

```bash
sudo journalctl -t weather-wifi-watchdog -f
```

Readings are never lost while the link is down. The client buffers 72 hours and
backfills with the original timestamps.

## Clock handling

A Raspberry Pi has no battery backed clock. After a power cut it restores the
time that systemd last recorded, then waits for NTP to correct it. A reading
taken in that window would carry a timestamp hours wrong.

The client stores such a reading as provisional, together with the
`CLOCK_BOOTTIME` value that produced it, and holds it back from upload. Once
NTP sets the clock, the client recovers the true timestamp from the monotonic
interval and releases the reading. A wrong timestamp never reaches the server.

Fit a real time clock module if you want to avoid the situation entirely.

## Dependencies

- `weatherhat` for the sensor.
- `httpx` for uploads.
- `psutil` for health reporting.

## Architecture

```
Client
├── Sensor reading, every 15 seconds
│   └── WeatherHAT over I2C and SPI
├── Local buffer in SQLite
│   └── 17280 readings, which is 72 hours
└── Upload, every 5 minutes
    └── HTTP POST in chunks
```
