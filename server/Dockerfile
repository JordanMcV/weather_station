# Dockerfile for Weather Server (Pi 4)

FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml ./
COPY README.md ./
COPY src/ ./src/

# Install dependencies using uv (no virtual environment in container)
RUN uv sync

# Create non-root user
RUN useradd --create-home --shell /bin/bash weather && \
    chown -R weather:weather /app
USER weather

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/api/v1/health || exit 1

# Run the server
CMD ["uv", "run", "python", "-m", "src.weather_server"]
