import time
import logging
import requests
from typing import Dict, Any, Optional, Generator, List, Tuple

from .exceptions import (
    RateLimitError,
    RetryableError,
    NetworkError,
    ServerError,
    GraphQLError,
    AuthenticationError,
    PermissionError,
    NotFoundError,
    FatalError
)
from .rate_limiter import RateLimiter
from github2ocel.config.context import RepoContext

logger = logging.getLogger(__name__)

class GitHubClient:
    def __init__(
        self,
        token: str,
        rest_url: str = "https://api.github.com",
        graphql_url: str = "https://api.github.com/graphql",
        timeout: int = 30,
        max_retries: int = 5,
        retry_backoff_min: float = 1.0,
        retry_backoff_max: float = 30.0,
        max_pages: Optional[int] = None,
        graphql_per_page: int = 50,
        rest_per_page: int = 100
    ):
        self.rest_url = rest_url.rstrip("/")
        self.graphql_url = graphql_url
        self.timeout = timeout
        self.token = token

        self.max_retries = max_retries
        self.retry_backoff_min = retry_backoff_min
        self.retry_backoff_max = retry_backoff_max
        self.max_pages = max_pages
        self.rest_per_page = rest_per_page
        self.graphql_per_page = graphql_per_page
        self.session = requests.Session()

        self._base_headers = {"Authorization": f"Bearer {token}"}

        self.rest_headers = {
            **self._base_headers,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.graphql_headers = self._base_headers.copy()

        self.limiter = RateLimiter()
        self.owner: Optional[str] = None
        self.repo: Optional[str] = None

    @classmethod
    def from_context(cls, ctx: RepoContext) -> "GitHubClient":
        client = cls(
            token=ctx.token,
            rest_url=ctx.api.rest_url,
            graphql_url=ctx.api.graphql_url,
            timeout=ctx.api.timeout,
            max_retries=ctx.api.max_retries,
            retry_backoff_min=ctx.api.retry_backoff_min,
            retry_backoff_max=ctx.api.retry_backoff_max,
            max_pages=ctx.api.max_pages,
            graphql_per_page=ctx.api.graphql_per_page,
            rest_per_page=ctx.api.rest_per_page
        )
        client.owner = ctx.owner
        client.repo = ctx.repo
        client._time_window = ctx.time_window_iso
        return client

    def close(self):
        self.session.close()

    @property
    def time_window_iso(self) -> Tuple[Optional[str], str]:
        """Returns (since_iso, until_iso) for use in queries."""
        return self._time_window

    @property
    def repo_path(self) -> str:
        """Returns /repos/{owner}/{repo} or raises if not configured."""
        if not self.owner or not self.repo:
            raise ValueError("Client not configured with owner/repo. Use from_context() or set manually.")
        return f"/repos/{self.owner}/{self.repo}"

    # Helper retry logic
    def _should_retry_http(self, status_code: int) -> bool:
        return status_code in (403, 429) or 500 <= status_code <= 599

    # REST GET
    def rest_get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        resource: str = "core",
    ) -> requests.Response:

        url = f"{self.rest_url}{endpoint}"
        params = params or {}

        for attempt in range(1, self.max_retries + 1):
            try:
                self.limiter.wait_if_needed(resource)

                try:
                    response = self.session.get(
                        url,
                        headers=self.rest_headers,
                        params=params,
                        timeout=self.timeout,
                    )

                    self.limiter.update_from_response(response, resource)
                except requests.RequestException as e:
                    self._handle_request_error(e)

                self.limiter.update_from_response(response, resource)

                # 4. Validate Status
                self._check_status_code(response)

                return response

            except RetryableError as e:
                # Catch NetworkError, RateLimitError, ServerError
                if attempt == self.max_retries:
                    logger.error(f"REST: Max retries reached ({self.max_retries}) for {url}")
                    raise e
                wait = min(self.retry_backoff_max, self.retry_backoff_min * (2 ** (attempt - 1)))
                logger.warning(f"REST Retry {attempt}/{self.max_retries} due to {type(e).__name__}: {e}. Waiting {wait}s...")
                time.sleep(wait)

            except FatalError as e:
                # Not retry: Auth, 404, etc.
                logger.error(f"REST Fatal Error: {e}")
                raise e

        raise RuntimeError("Unreachable REST loop")


    # REST pagination
    def rest_paginated(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        resource: str = "core",
        per_page: int = 100,
    ) -> Generator[List[Dict[str, Any]], None, None]:

        params = params or {}
        params["per_page"] = min(per_page, 100)  # GitHub max is 100
        page = 1

        while True:
            if self.max_pages and page > self.max_pages:
                logger.info(f"Reached max_pages limit ({self.max_pages})")
                break

            params["page"] = page
            response = self.rest_get(endpoint, params=params, resource=resource)
            data = response.json()

            if not isinstance(data, list) or not data:
                break

            yield data
            page += 1

    # GraphQL
    def graphql(
        self,
        query: str,
        variables: Dict[str, Any],
        resource: str = "graphql",
    ) -> Dict[str, Any]:

        for attempt in range(1, self.max_retries + 1):
            try:
                self.limiter.wait_if_needed(resource)

                try:

                    response = self.session.post(
                        self.graphql_url,
                        json={"query": query, "variables": variables},
                        headers=self.graphql_headers,
                        timeout=self.timeout,
                    )
                except requests.RequestException as e:
                    self._handle_request_error(e)

                self.limiter.update_from_response(response, resource)
                # Handle HTTP errors
                self._check_status_code(response)

                payload = response.json()

                # Handle GraphQL errors
                errors = payload.get("errors", [])
                if errors:
                    # Update limiter state before raising
                    self.limiter.update_from_graphql_errors(errors, resource)

                    err = errors[0]
                    msg = err.get("message", "GraphQL Error")
                    err_type = err.get("type")
                    path = err.get("path")

                    gql_exception = GraphQLError(msg, error_type=err_type, path=path)

                    # Decide if retryable
                    if gql_exception.is_retryable:
                        raise gql_exception
                    else:
                        # Fatal GraphQL error
                        logger.error(f"GraphQL Fatal: {gql_exception}")
                        raise gql_exception

                return payload

            except (RetryableError, GraphQLError) as e:

                # GraphQLError that does not inherit from RetryableError by default
                is_retryable = isinstance(e, RetryableError) or (isinstance(e, GraphQLError) and e.is_retryable)

                if not is_retryable:
                    raise e

                if attempt == self.max_retries:
                    raise e

                wait = min(self.retry_backoff_max, self.retry_backoff_min * (2 ** (attempt - 1)))
                logger.warning(f"GraphQL Retry {attempt}/{self.max_retries}: {e}. Waiting {wait}s...")
                time.sleep(wait)

        raise RuntimeError("Unreachable GraphQL loop")

    # Métodos Helpers para repos, issues, PRs, commits
    def get_repo(self) -> Dict[str, Any]:
        if not self.owner or not self.repo:
            raise ValueError("owner/repo not set")
        return self.rest_get(f"/repos/{self.owner}/{self.repo}").json()

    def get_issues(self, state: str = "open") -> Generator[List[Dict[str, Any]], None, None]:
        if not self.owner or not self.repo:
            raise ValueError("owner/repo not set")
        return self.rest_paginated(f"/repos/{self.owner}/{self.repo}/issues", params={"state": state})

    def get_pulls(self, state: str = "open") -> Generator[List[Dict[str, Any]], None, None]:
        if not self.owner or not self.repo:
            raise ValueError("owner/repo not set")
        return self.rest_paginated(f"/repos/{self.owner}/{self.repo}/pulls", params={"state": state})

    def get_commits(self, params: Optional[Dict[str, Any]] = None) -> Generator[List[Dict[str, Any]], None, None]:
        if not self.owner or not self.repo:
            raise ValueError("owner/repo not set")

        return self.rest_paginated(
            f"/repos/{self.owner}/{self.repo}/commits",
            params=params
        )
    
    def _handle_request_error(self, e: Exception) -> None:
        """Convert request errors in our hierarchy."""
        if isinstance(e, requests.Timeout):
            raise NetworkError(f"Timeout: {e}")
        if isinstance(e, requests.ConnectionError):
            raise NetworkError(f"Connection Error: {e}")
        # Si ya es una de nuestras excepciones, la dejamos pasar
        raise e

    def _check_status_code(self, response: requests.Response):
        """Handles HTTP codes and throws the correct exceptions."""
        code = response.status_code
        
        if 200 <= code < 300:
            return

        if code == 401:
            raise AuthenticationError("Invalid Token (401)")
        if code == 404:
            raise NotFoundError(f"Resource not found (404): {response.url}")
        if code == 403:
            # 403 Rate Limit (secondary) or Permiss
            msg = response.text
            if "rate limit" in msg.lower() or "secondary" in msg.lower():
                raise RateLimitError("Secondary Rate Limit (403)", resource="core")
            raise PermissionError("Permission Denied (403)")
        
        if code == 429:
            raise RateLimitError("Rate Limit Exceeded (429)", resource="core")
        
        if 500 <= code < 600:
            raise ServerError(f"GitHub Server Error ({code})")

        # Other errors
        response.raise_for_status()

    # Stadistics Rate Limit
    def print_rate_limit_stats(self):
        logger.info("=== Rate Limit Stats ===")
        logger.info(f"Total requests: {self.limiter.total_requests}")
        logger.info(f"Wait events:   {self.limiter.total_waits}")
        logger.info(f"Wait time:     {self.limiter.total_wait_time:.2f}s")
