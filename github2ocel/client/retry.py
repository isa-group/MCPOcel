import time
from typing import Callable, TypeVar

from .exceptions import FatalError, RetryableError, GraphQLError
from shared.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class RetryStrategy:

    def __init__(self, config):
        self.max_retries = config.max_retries
        self.backoff_min = config.retry_backoff_min
        self.backoff_max = config.retry_backoff_max

    def __iter__(self):
        for attempt in range(1, self.max_retries + 1):
            yield attempt

    def sleep(self, attempt: int) -> None:
        wait = min(
            self.backoff_max,
            self.backoff_min * (2 ** (attempt - 1))
        )
        time.sleep(wait)

    def run(self, fn: Callable[[], T]) -> T:
        """
        Execute fn() with exponential backoff retry.

        - FatalError       → re-raised immediately, no retry.
        - RetryableError   → retried up to max_retries times.
        - GraphQLError     → retried only if error.is_retryable is True.
        - Any other Exception → retried (unexpected transient failures).

        Raises the last exception if all attempts are exhausted.
        """
        last_exc: Exception = None

        for attempt in range(1, self.max_retries + 1):
            try:
                return fn()

            except FatalError:
                raise  # Never retry auth/permission/404 errors

            except GraphQLError as e:
                last_exc = e
                if not e.is_retryable:
                    raise
                logger.warning(
                    f"[retry] GraphQL retryable error on attempt {attempt}/{self.max_retries}: {e}"
                )

            except RetryableError as e:
                last_exc = e
                logger.warning(
                    f"[retry] Retryable error on attempt {attempt}/{self.max_retries}: {e}"
                )

            except Exception as e:
                last_exc = e
                logger.warning(
                    f"[retry] Unexpected error on attempt {attempt}/{self.max_retries}: {e}"
                )

            if attempt < self.max_retries:
                self.sleep(attempt)

        raise last_exc