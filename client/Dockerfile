# Dockerfile for Weather Client (Pi Zero)
# Optimized for ARM architecture and minimal size

FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy poetry files
COPY pyproject.toml poetry.lock* ./

# Install poetry and dependencies
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-dev --no-interaction --no-ansi

# Copy application code
COPY src/ ./src/

# Create data directory for SQLite database
RUN mkdir -p /data && chmod 777 /data

# Create non-root user
RUN useradd --create-home --shell /bin/bash weather && \
    chown -R weather:weather /app /data
USER weather

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/data/weather.db

# Run the client
CMD ["python", "-m", "weather_client"]
