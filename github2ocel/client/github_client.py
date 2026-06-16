import requests
from typing import Dict, Any, Optional, Generator, NoReturn

from github2ocel.config.context import RepoContext
from shared.telemetry.session_factory import SessionFactory

from .rate_limiter import RateLimiter
from .retry import RetryStrategy
from .exceptions import (
    GraphQLError, AuthenticationError, NotFoundError,
    ServerError, GitHubPermissionError, RateLimitError, NetworkError
)
from shared.logger import get_logger

logger = get_logger(__name__)

class GitHubClient:

    def __init__(self, ctx: RepoContext, extractor: Optional[str] = None):

        self.ctx    = ctx
        self.config = ctx.api
        self.owner  = ctx.owner
        self.repo   = ctx.repo

        self.session = SessionFactory.create(
            token     = ctx.token,
            owner     = ctx.owner,
            repo      = ctx.repo,
            extractor = extractor,
        )
        self.session.headers.update({
            "Authorization": f"Bearer {ctx.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.config.api_version
        })

        self.rate_limiter = RateLimiter()
        self.retry        = RetryStrategy(self.config)

    @classmethod
    def from_context(cls, ctx: RepoContext, extractor: Optional[str] = None) -> "GitHubClient":
        """
        Factory method — constructs a client from a RepoContext.
        Preferred over direct instantiation: allows pre-construction
        validation and is easier to mock in tests.
        """
        return cls(ctx, extractor=extractor)


    def _check_status_code(self, response: requests.Response) -> None:
        """Centralised HTTP error handling — raises the correct exception."""
        code = response.status_code

        if 200 <= code < 300:
            return

        if code == 401:
            raise AuthenticationError("Invalid token (401)")

        if code == 403:
            msg = response.text.lower()
            if "rate limit" in msg or "secondary" in msg:
                raise RateLimitError("Secondary rate limit (403)", resource="core")
            raise GitHubPermissionError("Permission denied (403)")

        if code == 404:
            raise NotFoundError(f"Resource not found (404): {response.url}")

        if code == 429:
            raise RateLimitError("Rate limit exceeded (429)", resource="core")

        if 500 <= code < 600:
            raise ServerError(f"GitHub server error ({code})")

        response.raise_for_status()


    #  Public API
    def rest(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:

        url = f"{self.config.rest_url}{path}"

        def _request():
            self.rate_limiter.wait_if_needed("core")
            try:
                r = self.session.get(url, params=params, timeout=self.config.timeout)
            except Exception as e:
                self._handle_request_error(e)
            self.rate_limiter.update_from_response(r, "core")
            self._check_status_code(r)
            return r.json()

        return self.retry.run(_request)

    def rest_paginated(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        per_page: int = 100,
    ) -> Generator[list, None, None]:
        """Yields one page (list) at a time using page-number pagination."""
        page    = 1
        params_ = {"per_page": per_page, "page": page, **(params or {})}

        while True:
            result = self.rest(endpoint, params=params_)
            if not result:
                break
            yield result
            if len(result) < per_page:
                break
            page += 1
            params_["page"] = page

    def graphql(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        def _request():
            self.rate_limiter.wait_if_needed("graphql")
            try:
                r = self.session.post(
                    self.config.graphql_url,
                    json={"query": query, "variables": variables or {}},
                    timeout=self.config.timeout,
                )
            except Exception as e:
                self._handle_request_error(e)

            self.rate_limiter.update_from_response(r, "graphql")
            self._check_status_code(r)

            data = r.json()

            if "errors" in data:
                self.rate_limiter.update_from_graphql_errors(data["errors"])
                err = data["errors"][0]
                raise GraphQLError(
                    err.get("message"),
                    err.get("type"),
                    err.get("path"),
                )

            payload = data["data"]

            self.rate_limiter.update_from_graphql_body(payload)
            return payload

        return self.retry.run(_request)

    # Convenience properties — delegate to ctx / ctx.api
    @property
    def time_window_iso(self):
        return self.ctx.time_window_iso

    @property
    def rest_per_page(self) -> int:
        return self.ctx.api.rest_per_page

    @property
    def graphql_per_page(self) -> int:
        return self.ctx.api.graphql_per_page

    @property
    def max_pages(self):
        return self.ctx.api.max_pages

    # Lifecycle
    def print_rate_limit_stats(self) -> None:
        logger.info("--- Rate Limit Stats ---")
        logger.info(f"  Total requests : {self.rate_limiter.total_requests}")
        logger.info(f"  Wait events    : {self.rate_limiter.total_waits}")
        logger.info(f"  Wait time      : {self.rate_limiter.total_wait_time:.2f}s")

    def close(self) -> None:
        self.session.close()

    def _handle_request_error(self, e: Exception) -> NoReturn:
        """Convert request errors into our exception hierarchy. Always raises."""
        if isinstance(e, requests.Timeout):
            raise NetworkError(f"Timeout: {e}")
        if isinstance(e, requests.ConnectionError):
            raise NetworkError(f"Connection Error: {e}")
        if isinstance(e, requests.exceptions.ChunkedEncodingError):
            raise NetworkError(f"Server Connection Broken (ChunkedEncodingError): {e}")
        raise e