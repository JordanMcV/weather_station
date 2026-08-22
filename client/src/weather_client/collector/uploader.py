"""HTTP uploader for weather data batches."""

import asyncio
import gzip
import logging
import httpx

from ..config import Config
from ..models import WeatherBatch


logger = logging.getLogger(__name__)

# Batches smaller than this compress to more bytes than they save.
GZIP_MIN_READINGS = 10


class WeatherUploader:
    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.api_key}",
            }
        )

    async def upload_batch(self, batch: WeatherBatch) -> bool:
        """Upload a batch of weather readings with retry logic."""
        body, headers = self._encode(batch.to_json(), compress=len(batch.readings) >= GZIP_MIN_READINGS)
        return await self._post(
            "/api/v1/weather/batch",
            body,
            headers,
            description=f"batch {batch.batch_id}",
        )

    def _encode(self, payload: str, compress: bool):
        """Encode a JSON payload, compressing it when it is worth the CPU cost."""
        raw = payload.encode("utf-8")
        if not compress:
            return raw, {}
        return gzip.compress(raw), {"Content-Encoding": "gzip"}

    async def _post(self, path: str, body: bytes, headers: dict, description: str) -> bool:
        """POST a payload with retry and exponential backoff."""
        url = f"{self.config.server_url}{path}"

        for attempt in range(self.config.retry_attempts):
            try:
                response = await self.client.post(url, content=body, headers=headers)

                if response.status_code == 200:
                    logger.debug(f"Successfully uploaded {description}")
                    return True
                elif response.status_code == 401:
                    logger.error("Authentication failed - check API key")
                    return False
                elif response.status_code == 400:
                    logger.error(f"Bad request uploading {description}: {response.text}")
                    return False
                else:
                    logger.warning(f"Upload of {description} failed with status {response.status_code}: {response.text}")

            except httpx.TimeoutException:
                logger.warning(f"Upload timeout on attempt {attempt + 1} for {description}")
            except httpx.ConnectError:
                logger.warning(f"Connection error on attempt {attempt + 1} for {description}")
            except Exception as e:
                logger.error(f"Unexpected error on attempt {attempt + 1} for {description}: {e}")

            # Calculate delay for exponential backoff
            if attempt < self.config.retry_attempts - 1:
                delay = min(
                    self.config.retry_base_delay * (2 ** attempt),
                    self.config.retry_max_delay
                )
                logger.info(f"Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)

        logger.error(f"Failed to upload {description} after {self.config.retry_attempts} attempts")
        return False

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
