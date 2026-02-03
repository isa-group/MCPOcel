import logging
import time
import requests
from typing import List, Dict, Any, Optional

from github2ocel.config.settings import APIConfig
from github2ocel.extractor.rate_limiter import get_rate_limiter, RateLimitException

logger = logging.getLogger(__name__)

def rest_get(
    endpoint: str,
    token: str,
    api_config: APIConfig,
    params: Optional[Dict[str, Any]] = None,
    resource: str = 'core'
) -> requests.Response:
    """
    Generic REST GET requester with integrated RateLimiting and Retries.
    """
    limiter = get_rate_limiter()
    url = f"{api_config.rest_url}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    params = params or {}

    for attempt in range(1, api_config.max_retries + 1):
        try:
            # 1. Proactive wait: Check if we have quota BEFORE calling
            limiter.wait_if_needed(resource)

            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=api_config.timeout,
            )

            # 2. Update limiter state with real headers from GitHub
            limiter.update_from_response(response, resource)

            # 3. Handle specific rate limit status codes (403/429)
            if response.status_code in (403, 429):
                logger.warning(f"Rate limit hit (HTTP {response.status_code}). Retrying phase...")
                # The next loop iteration will call wait_if_needed()
                # which now knows about the exhaustion thanks to update_from_response
                continue

            response.raise_for_status()
            return response

        except (requests.RequestException, RateLimitException) as e:
            if attempt == api_config.max_retries:
                logger.error(f"REST Request failed permanently after {attempt} attempts: {url}")
                raise e

            # Exponential Backoff for network errors
            wait = min(
                api_config.retry_backoff_max,
                api_config.retry_backoff_min * (2 ** (attempt - 1))
            )
            logger.warning(f"Attempt {attempt} failed. Retrying in {wait}s... Error: {e}")
            time.sleep(wait)

    raise RuntimeError("Unreachable REST client state")


def print_rate_limit_stats():
    """Helper to show final stats in main.py"""
    limiter = get_rate_limiter()
    stats = limiter.get_stats()
    logger.info("Final Rate Limit Stats:")
    logger.info(f" - Total Requests: {stats['total_requests']}")
    logger.info(f" - Wait events: {stats['total_waits']}")
    logger.info(f" - Total time spent waiting: {stats['total_wait_time']:.2f}s")