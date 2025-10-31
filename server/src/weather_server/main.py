#!/usr/bin/env python3
"""Weather Server - Main entry point for Pi 5 server."""

import logging
import sys
from argparse import ArgumentParser

import uvicorn

from .config import Config
from .api.app import create_app


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
    parser = ArgumentParser(description="Weather Server: Pi 5 weather data ingestion API")

    parser.add_argument(
        "--host",
        help="Server host to bind to"
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Server port to bind to"
    )
    parser.add_argument(
        "--influxdb-url",
        help="InfluxDB connection URL"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level"
    )

    return parser


def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Load configuration from environment
    config = Config.from_env()

    # Override config with command line arguments
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.influxdb_url:
        config.influxdb_url = args.influxdb_url
    if args.log_level:
        config.log_level = args.log_level

    # Setup logging
    setup_logging(config.log_level)
    logger = logging.getLogger(__name__)

    logger.info(f"Starting Weather Server on {config.host}:{config.port}")

    # Create FastAPI app
    app = create_app(config)

    try:
        # Run the server
        uvicorn.run(
            app,
            host=config.host,
            port=config.port,
            log_level=config.log_level.lower(),
            access_log=True
        )
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
