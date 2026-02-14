import time
import logging
import requests
from typing import Dict, Any, List
from .exceptions import RateLimitError

logger = logging.getLogger(__name__)

class RateLimiter:
    """
    Manage GitHub limits by resource: core, search, graphql
    """
    def __init__(self):
        self.resources = {
            "core": {"remaining": None, "reset": None},
            "search": {"remaining": None, "reset": None},
            "graphql": {"remaining": None, "reset": None},
        }
        self.total_requests = 0
        self.total_waits = 0
        self.total_wait_time = 0.0

    def wait_if_needed(self, resource: str):
        data = self.resources.get(resource, {})
        remaining = data.get("remaining")
        reset = data.get("reset")

        if remaining is None or reset is None:
            return

        if remaining > 0:
            return

        now = int(time.time())
        sleep_time = max(0, reset - now) + 1
        if sleep_time > 0:
            logger.warning(f"[{resource}] Waiting {sleep_time}s due to rate limit…")
            self.total_waits += 1
            self.total_wait_time += sleep_time
            time.sleep(sleep_time)

    def update_from_response(self, response: requests.Response, resource: str):
        try:
            self.resources[resource]["remaining"] = int(response.headers.get("X-RateLimit-Remaining"))
            self.resources[resource]["reset"] = int(response.headers.get("X-RateLimit-Reset"))
        except (TypeError, ValueError):
            logger.debug("Rate limit headers not present")

        self.total_requests += 1


    def update_from_graphql_errors(self, errors: List[Dict[str, Any]], resource: str = "graphql"):
        for err in errors:
            if err.get("type") == "RATE_LIMITED":
                raise RateLimitError("GraphQL rate limit", resource=resource)