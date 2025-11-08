"""HTTP uploader for weather data batches."""

import asyncio
import logging
import httpx

from ..config import Config
from ..models import WeatherBatch


logger = logging.getLogger(__name__)


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
        for attempt in range(self.config.retry_attempts):
            try:
                response = await self.client.post(
                    f"{self.config.server_url}/api/v1/weather/batch",
                    content=batch.to_json(),
                    headers={"Content-Encoding": "gzip"} if len(batch.readings) > 10 else {}
                )

                if response.status_code == 200:
                    logger.debug(f"Successfully uploaded batch {batch.batch_id}")
                    return True
                elif response.status_code == 401:
                    logger.error("Authentication failed - check API key")
                    return False
                elif response.status_code == 400:
                    logger.error(f"Bad request: {response.text}")
                    return False
                else:
                    logger.warning(f"Upload failed with status {response.status_code}: {response.text}")

            except httpx.TimeoutException:
                logger.warning(f"Upload timeout on attempt {attempt + 1}")
            except httpx.ConnectError:
                logger.warning(f"Connection error on attempt {attempt + 1}")
            except Exception as e:
                logger.error(f"Unexpected error on attempt {attempt + 1}: {e}")

            # Calculate delay for exponential backoff
            if attempt < self.config.retry_attempts - 1:
                delay = min(
                    self.config.retry_base_delay * (2 ** attempt),
                    self.config.retry_max_delay
                )
                logger.info(f"Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)

        logger.error(f"Failed to upload batch {batch.batch_id} after {self.config.retry_attempts} attempts")
        return False

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
