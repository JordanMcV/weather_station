#!/usr/bin/env python3
"""Weather Client - Main entry point for Pi Zero collector."""

import asyncio
import logging
import signal
import sys
from argparse import ArgumentParser

from .config import Config
from .collector.service import WeatherCollector


def setup_logging(level: str):
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
        ]
    )


def create_parser() -> ArgumentParser:
    """Create command line argument parser."""
    parser = ArgumentParser(description="Weather Client: Pi Zero weather data collector")

    parser.add_argument(
        "--server-url",
        help="URL of the weather data server"
    )
    parser.add_argument(
        "--api-key",
        help="API key for authentication"
    )
    parser.add_argument(
        "--upload-interval",
        type=int,
        help="Upload interval in seconds"
    )
    parser.add_argument(
        "--database-path",
        help="Path to SQLite database file"
    )
    parser.add_argument(
        "--station-id",
        help="Station identifier"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show collector status and exit"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level"
    )

    return parser


async def run_collector(config: Config, show_status: bool = False):
    """Run the weather collector."""
    collector = WeatherCollector(config)

    if show_status:
        # Show status and exit
        status = collector.get_status()
        print(f"Station ID: {status.station_id}")
        print(f"CPU: {status.cpu_percent:.1f}%")
        print(f"Memory: {status.memory_percent:.1f}%")
        print(f"Disk: {status.disk_percent:.1f}%")
        if status.temperature:
            print(f"CPU Temperature: {status.temperature:.1f}°C")
        print(f"Network: {'Connected' if status.network_connected else 'Disconnected'}")
        print(f"Buffer Size: {status.buffer_size} readings")
        if status.last_upload:
            print(f"Last Upload: {status.last_upload}")
        else:
            print("Last Upload: Never")
        return

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logging.info(f"Received signal {signum}, shutting down...")
        asyncio.create_task(collector.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await collector.start()
    except KeyboardInterrupt:
        logging.info("Shutting down collector...")
    except Exception as e:
        logging.error(f"Collector error: {e}")
        raise


def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Load configuration from environment
    config = Config.from_env()

    # Override config with command line arguments
    if args.server_url:
        config.server_url = args.server_url
    if args.api_key:
        config.api_key = args.api_key
    if args.upload_interval:
        config.upload_interval = args.upload_interval
    if args.database_path:
        config.database_path = args.database_path
    if args.station_id:
        config.station_id = args.station_id
    if args.log_level:
        config.log_level = args.log_level

    # Setup logging
    setup_logging(config.log_level)
    logger = logging.getLogger(__name__)

    logger.info(f"Starting Weather Client (Station: {config.station_id})")

    try:
        asyncio.run(run_collector(config, args.status))
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
