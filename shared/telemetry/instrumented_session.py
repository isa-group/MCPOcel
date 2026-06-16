"""
shared/telemetry/instrumented_session.py
-----------------------------------------
Drop-in replacement for `requests.Session` with OTel instrumentation.

Differences from the standalone version (api-digital-twin/Phase 1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* `MiddlewareConfig` includes `owner`, `repo` and `extractor` — the
  semantic context fields that are only accessible from within the process.
* The resulting `ApiCallEvent` has these fields populated, allowing
  the twin to answer questions such as:
      ‘Which extractor is draining the core bucket the fastest?’
      ‘Which repos have anomalous consumption patterns?’
* In the event of a network exception, a partial event is still emitted with
  `status_code=0` so that the twin can also model failures.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from pydantic import BaseModel

from shared.telemetry.schema import (
    ApiCallEvent,
    ApiTarget,
    GitHubRateLimitHeaders,
    GraphQLCost,
    HttpMethod,
    ThrottleSignal,
)
from shared.store.jsonl_store import TelemetryStore


# ---------------------------------------------------------------------------
# Normalized endpoint 
# ---------------------------------------------------------------------------

_GITHUB_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"/repos/[^/]+/[^/]+/commits/[0-9a-f]{4,}"),      "/repos/{owner}/{repo}/commits/{sha}"),
    (re.compile(r"/repos/[^/]+/[^/]+/git/commits/[0-9a-f]{4,}"),  "/repos/{owner}/{repo}/git/commits/{sha}"),
    (re.compile(r"/repos/[^/]+/[^/]+/issues/comments/\d+"),        "/repos/{owner}/{repo}/issues/comments/{id}"),
    (re.compile(r"/repos/[^/]+/[^/]+/pulls/comments/\d+"),         "/repos/{owner}/{repo}/pulls/comments/{id}"),
    (re.compile(r"/repos/[^/]+/[^/]+/issues/\d+"),                 "/repos/{owner}/{repo}/issues/{number}"),
    (re.compile(r"/repos/[^/]+/[^/]+/pulls/\d+"),                  "/repos/{owner}/{repo}/pulls/{number}"),
    (re.compile(r"/repos/[^/]+/[^/]+/releases/\d+"),               "/repos/{owner}/{repo}/releases/{id}"),
    (re.compile(r"/repos/[^/]+/[^/]+/milestones/\d+"),             "/repos/{owner}/{repo}/milestones/{number}"),
    (re.compile(r"/repos/[^/]+/[^/]+/labels/[^/?]+"),              "/repos/{owner}/{repo}/labels/{name}"),
    (re.compile(r"/repos/[^/]+/[^/]+"),                            "/repos/{owner}/{repo}"),
    (re.compile(r"/users/[^/?]+"),                                  "/users/{username}"),
    (re.compile(r"/orgs/[^/?]+"),                                   "/orgs/{org}"),
]

_DBLP_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"/search/publ/api"), "/search/publ/api"),
    (re.compile(r"/rec/[^?]+"),       "/rec/{key}"),
]


def _normalise_endpoint(url: str, api_target: ApiTarget) -> str:
    from urllib.parse import urlparse
    path = urlparse(url).path
    patterns = _GITHUB_PATTERNS if api_target == ApiTarget.GITHUB else _DBLP_PATTERNS
    for regex, template in patterns:
        if regex.search(path):
            return regex.sub(template, path)
    return path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class MiddlewareConfig(BaseModel):
    """
    Configuring `InstrumentedSession`.

    The `owner`, `repo` and `extractor` fields are optional but
    enrich the telemetry when used with github2ocel.
    """
    model_config = {"arbitrary_types_allowed": True}

    api_target:       ApiTarget
    consumer_id:      str
    store:            TelemetryStore
    owner:            Optional[str] = None
    repo:             Optional[str] = None
    extractor:        Optional[str] = None
    tracer_provider:  Any           = None


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class InstrumentedSession(requests.Session):
    """
    A drop-in replacement for `requests.Session` that:

    1. Opens an OTel span for each HTTP call.
    2. Extracts X-RateLimit-* headers and throttling signals.
    3. Constructs an `ApiCallEvent` enriched with semantic context
       (owner, repo, extractor) and persists it in the `TelemetryStore`.
    4. Marks the span as ERROR on 4xx/5xx responses for traceability.

    All of this is transparent to the caller.
    """

    def __init__(self, config: MiddlewareConfig) -> None:
        super().__init__()
        self._config = config

        if config.tracer_provider is None:
            self._span_exporter = InMemorySpanExporter()
            provider = TracerProvider()
            provider.add_span_processor(SimpleSpanProcessor(self._span_exporter))
            self._tracer_provider = provider
        else:
            self._tracer_provider = config.tracer_provider
            self._span_exporter = None

        self._tracer = self._tracer_provider.get_tracer("api_digital_twin")

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        endpoint_pattern = _normalise_endpoint(url, self._config.api_target)
        span_name = f"{method.upper()} {endpoint_pattern}"

        with self._tracer.start_as_current_span(span_name) as span:
            # Standard OTel attributes
            span.set_attribute("http.method",    method.upper())
            span.set_attribute("http.url",       url)
            span.set_attribute("http.target",    endpoint_pattern)
            span.set_attribute("dt.api_target",  self._config.api_target.value)

            # Semantic context — available only with direct integration
            if self._config.owner:
                span.set_attribute("dt.owner",     self._config.owner)
            if self._config.repo:
                span.set_attribute("dt.repo",      self._config.repo)
            if self._config.extractor:
                span.set_attribute("dt.extractor", self._config.extractor)

            t_start  = time.perf_counter()
            ts_utc   = datetime.now(timezone.utc)
            response = None

            try:
                response = super().request(method, url, **kwargs)
            except requests.RequestException as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                # Persist partial events to model network failures
                self._persist_error_event(
                    span, ts_utc, t_start, method, url, endpoint_pattern, exc
                )
                raise

            latency_ms = (time.perf_counter() - t_start) * 1000.0

            span.set_attribute("http.status_code",         response.status_code)
            span.set_attribute("http.response_latency_ms", round(latency_ms, 2))

            if response.status_code >= 400:
                span.set_status(StatusCode.ERROR, f"HTTP {response.status_code}")
            else:
                span.set_status(StatusCode.OK)

            # Rate-limit headers
            github_rl: Optional[GitHubRateLimitHeaders] = None
            bucket_id = "default"

            if self._config.api_target == ApiTarget.GITHUB:
                github_rl = GitHubRateLimitHeaders.from_response_headers(
                    dict(response.headers)
                )
                bucket_id = self._resolve_bucket(github_rl)
                self._set_ratelimit_span_attrs(span, github_rl)

            # Throttling
            throttle = ThrottleSignal(
                was_throttled       = response.status_code in (429, 403),
                retry_after_seconds = self._parse_retry_after(response),
                was_cached          = response.status_code == 304,
            )
            if throttle.was_throttled:
                span.add_event("throttled", {"status_code": response.status_code})

            # GraphQL cost
            graphql_cost: Optional[GraphQLCost] = None
            if self._config.api_target == ApiTarget.GITHUB and "graphql" in url:
                graphql_cost = self._extract_graphql_cost(response)

            # span IDs
            ctx        = span.get_span_context()
            span_id    = format(ctx.span_id,  "016x") if ctx.is_valid else "0" * 16
            trace_id   = format(ctx.trace_id, "032x") if ctx.is_valid else "0" * 32

            event = ApiCallEvent(
                event_id          = span_id,
                trace_id          = trace_id,
                consumer_id       = self._config.consumer_id,
                api_target        = self._config.api_target,
                # Semantic context — only available with direct integration
                owner             = self._config.owner,
                repo              = self._config.repo,
                extractor         = self._config.extractor,
                # Request
                timestamp_utc     = ts_utc,
                method            = HttpMethod(method.upper()),
                endpoint_pattern  = endpoint_pattern,
                url               = url,
                # Response
                status_code       = response.status_code,
                latency_ms        = round(latency_ms, 2),
                # Rate-limit
                github_rate_limit = github_rl,
                throttle_signal   = throttle,
                graphql_cost      = graphql_cost,
                bucket_id         = bucket_id,
                span_id           = span_id,
            )
            self._config.store.append(event)
            return response

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_bucket(rl: GitHubRateLimitHeaders) -> str:
        if rl.resource is None:
            return "core"
        return rl.resource.value if hasattr(rl.resource, "value") else str(rl.resource)

    @staticmethod
    def _set_ratelimit_span_attrs(span: Any, rl: GitHubRateLimitHeaders) -> None:
        if rl.remaining  is not None: span.set_attribute("ratelimit.remaining",  rl.remaining)
        if rl.limit      is not None: span.set_attribute("ratelimit.limit",      rl.limit)
        if rl.reset_unix is not None: span.set_attribute("ratelimit.reset_unix", rl.reset_unix)
        if rl.used       is not None: span.set_attribute("ratelimit.used",       rl.used)
        if rl.resource   is not None:
            span.set_attribute(
                "ratelimit.resource",
                rl.resource.value if hasattr(rl.resource, "value") else str(rl.resource),
            )

    @staticmethod
    def _parse_retry_after(response: requests.Response) -> Optional[int]:
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    @staticmethod
    def _extract_graphql_cost(response: requests.Response) -> Optional[GraphQLCost]:
        try:
            body = response.json()
            rl   = body.get("data", {}).get("rateLimit", {})
            if rl:
                return GraphQLCost(
                    points_consumed = rl.get("cost"),
                    points_limit    = rl.get("limit"),
                )
        except Exception:
            pass
        return None

    def _persist_error_event(
        self,
        span:             Any,
        ts_utc:           datetime,
        t_start:          float,
        method:           str,
        url:              str,
        endpoint_pattern: str,
        exc:              Exception,
    ) -> None:
        """Persist partial events when there are network errors (status_code=0)."""
        ctx      = span.get_span_context()
        span_id  = format(ctx.span_id,  "016x") if ctx.is_valid else "0" * 16
        trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else "0" * 32
        latency  = (time.perf_counter() - t_start) * 1000.0
        try:
            event = ApiCallEvent(
                event_id         = span_id,
                trace_id         = trace_id,
                consumer_id      = self._config.consumer_id,
                api_target       = self._config.api_target,
                owner            = self._config.owner,
                repo             = self._config.repo,
                extractor        = self._config.extractor,
                timestamp_utc    = ts_utc,
                method           = HttpMethod(method.upper()),
                endpoint_pattern = endpoint_pattern,
                url              = url,
                status_code      = 0,
                latency_ms       = round(latency, 2),
                bucket_id        = "unknown",
                span_id          = span_id,
                throttle_signal  = ThrottleSignal(was_throttled=False),
            )
            self._config.store.append(event)
        except Exception:
            pass  # Never block the caller due to telemetry errors

    def get_recorded_spans(self) -> list[Any]:
        """Returns the spans captured by the exporter in memory (useful in tests)."""
        if self._span_exporter is None:
            return []
        return self._span_exporter.get_finished_spans()
