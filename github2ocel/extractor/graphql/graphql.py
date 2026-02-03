import logging
import time
import requests
from typing import Dict, Any

from github2ocel.config.settings import APIConfig
from github2ocel.extractor.rate_limiter import get_rate_limiter, RateLimitException

logger = logging.getLogger(__name__)

def graphql_query(
    query: str,
    variables: Dict[str, Any],
    token: str,
    api_config: APIConfig,
    resource: str = "graphql",
) -> Dict[str, Any]:
    limiter = get_rate_limiter()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    for attempt in range(1, api_config.max_retries + 1):
        try:
            limiter.wait_if_needed(resource)

            response = requests.post(
                api_config.graphql_url,
                json={"query": query, "variables": variables},
                headers=headers,
                timeout=api_config.timeout,
            )

            limiter.update_from_response(response, resource)

            if response.status_code in (403, 429):
                logger.warning(f"GraphQL HTTP rate limit hit ({response.status_code})")
                continue

            response.raise_for_status()
            payload = response.json()

            if "errors" in payload:
                for error in payload["errors"]:
                    limiter.update_from_graphql_error(error, resource)

                    msg = error.get("message", "").lower()
                    if "rate limit" in msg:
                        logger.warning("GraphQL rate limit detected in payload")
                        break
                else:
                    raise RuntimeError(payload["errors"][0].get("message"))
                continue

            return payload.get("data", {})

        except (requests.RequestException, RuntimeError, RateLimitException) as e:
            if attempt == api_config.max_retries:
                logger.error("GraphQL failed permanently")
                raise

            wait = min(
                api_config.retry_backoff_max,
                api_config.retry_backoff_min * (2 ** (attempt - 1)),
            )
            logger.warning(f"GraphQL retry {attempt}, waiting {wait}s: {e}")
            time.sleep(wait)

    return {}
