import time
import random
import requests
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from .exceptions import RateLimitError
from shared.logger import get_logger

logger = get_logger(__name__)

class RateLimiter:

    GRAPHQL_LOW_WATER = 200  # Proactive sleep threshold

    def __init__(self):

        self.resources = {
            "core":    {},
            "search":  {},
            "graphql": {},
        }

        self.total_requests   = 0
        self.total_waits      = 0
        self.total_wait_time  = 0.0
        self._last_graphql_cost: int = 0

    #  Reactive throttle — called BEFORE each request
    def wait_if_needed(self, resource: str) -> None:

        data      = self.resources.get(resource, {})
        remaining = data.get("remaining")
        reset     = data.get("reset")

        if remaining is None or reset is None:
            return

        if remaining > 0:
            return

        now       = int(time.time())
        raw_sleep = max(0, reset - now) + 1
        sleep_time = raw_sleep * random.uniform(0.5, 1.5)
        reset_str  = time.strftime("%H:%M:%S", time.localtime(reset))

        logger.warning(
            f"[{resource}] Rate limit exhausted — "
            f"remaining={remaining} | "
            f"resets at {reset_str} (in {raw_sleep}s) | "
            f"sleeping {sleep_time:.1f}s"
        )

        self.total_waits      += 1
        self.total_wait_time  += sleep_time
        time.sleep(sleep_time)

    #  Update from REST / GraphQL HTTP headers
    def update_from_response(self, response: requests.Response, resource: str) -> None:

        remaining = response.headers.get("X-RateLimit-Remaining")
        reset     = response.headers.get("X-RateLimit-Reset")

        if remaining and reset:
            try:
                self.resources[resource]["remaining"] = int(remaining)
                self.resources[resource]["reset"]     = int(reset)
            except ValueError:
                logger.debug("Invalid rate limit headers")

        retry_after = response.headers.get("Retry-After")
        if retry_after:
            sleep_time = int(retry_after)
            logger.warning(f"[{resource}] Retry-After header. Sleeping {sleep_time}s")
            time.sleep(sleep_time)

        self.total_requests += 1

     #  Update from GraphQL response body  (cost + remaining + resetAt)
    def update_from_graphql_body(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Reads rateLimit { cost remaining resetAt } from the GraphQL response body.
        Returns a dict with the parsed values so the paginator can log them,
        or None if rateLimit is not present in the response.

        Proactively sleeps when remaining points fall below GRAPHQL_LOW_WATER
        so we never hit the hard limit mid-extraction.
        """
        rate_limit = payload.get("rateLimit")  # payload is already data["data"]
        if not rate_limit:
            return None

        cost      = rate_limit.get("cost", 1)
        remaining = rate_limit.get("remaining")
        reset_at  = rate_limit.get("resetAt")   # ISO 8601 string

        self._last_graphql_cost = cost

        if remaining is None:
            return None

        # Parse reset timestamp
        reset_ts: Optional[datetime] = None
        if reset_at:
            try:
                reset_ts = datetime.strptime(reset_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                self.resources["graphql"]["reset"] = int(reset_ts.timestamp())
            except ValueError:
                logger.debug(f"Failed to parse resetAt: {reset_at}")

        self.resources["graphql"]["remaining"] = remaining

        logger.debug(f"[graphql_rl] cost={cost} remaining={remaining}")

        # Proactive throttle: pause when approaching the limit
        if remaining < self.GRAPHQL_LOW_WATER and reset_ts:
            now        = datetime.now(timezone.utc)
            sleep_time = max((reset_ts - now).total_seconds(), 0) + 2

            logger.warning(
                f"[rate_limit] GraphQL points low ({remaining} < {self.GRAPHQL_LOW_WATER}) "
                f"— sleeping {sleep_time:.1f}s until reset at "
                f"{reset_ts.strftime('%H:%M:%S')}"
            )

            self.total_waits      += 1
            self.total_wait_time  += sleep_time
            time.sleep(sleep_time)
            self.resources["graphql"]["remaining"] = None  # force refresh next request

        return {"cost": cost, "remaining": remaining, "reset_at": reset_at}


    #  GraphQL error handling
    def update_from_graphql_errors(
        self,
        errors: List[Dict[str, Any]],
        resource: str = "graphql"
    ) -> None:

        for err in errors:
            if err.get("type") == "RATE_LIMITED":
                logger.warning("GraphQL rate limit triggered")
                raise RateLimitError("GraphQL rate limit", resource=resource)

    #  Soft throttle
    def soft_throttle(self) -> None:
        if self.total_requests % 50 == 0:
            sleep = random.uniform(0.5, 1.5)
            logger.debug(f"Soft throttle {sleep:.2f}s")
            time.sleep(sleep)