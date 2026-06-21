"""
shared/telemetry/instrumented_session.py
-----------------------------------------
Drop-in replacement for `requests.Session` with instrumentation.

Main flow
----------
    InstrumentedSession.request()
           ↓
    ApiCallEvent  (con run_id, owner, repo, extractor del contexto)
           ↓
    TelemetryStore.append()  →  in-memory queue  →  writer thread  →  JSONL

OTel — optional dependency
--------------------------
OTel is used if installed, but is NOT a mandatory dependency.
The `ApiCallEvent → TelemetryStore` flow works the same without it.
If OTel is not available, spans are simply not emitted.
To install OTel support:
    pip install opentelemetry-sdk

run_id
------
Each instance of `InstrumentedSession` carries a `run_id` that identifies
the entire pipeline execution (e.g. a github2ocel extraction).
It is generated automatically if not provided.
It allows us to answer: “How much did this execution cost?”, even if the same
(owner, repo, extractor) has been extracted multiple times.

Extractor
---------
Not set at build time — it is read from `telemetry_context` on each
call via `contextvars`. A session can be reused by
several extractors, and each event carries the correct extractor.
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from pydantic import BaseModel

from shared.telemetry.schema import (
    ApiCallEvent, ApiTarget, GitHubRateLimitHeaders,
    GraphQLCost, HttpMethod, ThrottleSignal,
)
from shared.store.jsonl_store import TelemetryStore
from shared.telemetry.session_factory import get_current_extractor


# ---------------------------------------------------------------------------
# OTel — import opcional
# ---------------------------------------------------------------------------

try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.trace import StatusCode
    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Normalized endpoint 
# ---------------------------------------------------------------------------

_GITHUB_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"/repos/[^/]+/[^/]+/commits/[0-9a-f]{4,}"),        "/repos/{owner}/{repo}/commits/{sha}"),
    (re.compile(r"/repos/[^/]+/[^/]+/git/commits/[0-9a-f]{4,}"),    "/repos/{owner}/{repo}/git/commits/{sha}"),
    (re.compile(r"/repos/[^/]+/[^/]+/issues/comments/\d+"),         "/repos/{owner}/{repo}/issues/comments/{id}"),
    (re.compile(r"/repos/[^/]+/[^/]+/pulls/comments/\d+"),          "/repos/{owner}/{repo}/pulls/comments/{id}"),
    (re.compile(r"/repos/[^/]+/[^/]+/issues/\d+"),                  "/repos/{owner}/{repo}/issues/{number}"),
    (re.compile(r"/repos/[^/]+/[^/]+/pulls/\d+"),                   "/repos/{owner}/{repo}/pulls/{number}"),
    (re.compile(r"/repos/[^/]+/[^/]+/releases/\d+"),                "/repos/{owner}/{repo}/releases/{id}"),
    (re.compile(r"/repos/[^/]+/[^/]+/milestones/\d+"),              "/repos/{owner}/{repo}/milestones/{number}"),
    (re.compile(r"/repos/[^/]+/[^/]+/labels/[^/?]+"),               "/repos/{owner}/{repo}/labels/{name}"),
    (re.compile(r"/repos/[^/]+/[^/]+"),                             "/repos/{owner}/{repo}"),
    (re.compile(r"/users/[^/?]+"),                                  "/users/{username}"),
    (re.compile(r"/orgs/[^/?]+"),                                   "/orgs/{org}"),
    (re.compile(r"/repos/[^/]+/[^/]+/actions/runs/\d+/jobs"),       "/repos/{owner}/{repo}/actions/runs/{run_id}/jobs")
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
   Configuration of `InstrumentedSession`.

    run_id:
        Run identifier. Groups all events from the same
        extraction to answer the question “How much did this run cost?”.
        Generated automatically if not provided (compact uuid4).
    owner / repo:
        Semantic context of the repository. Enriches each event.
    token_hash:
        Short hash of the token. Audit metadata to detect rotations.
        This is not the consumer’s identity (that is the `consumer_id`).
    tracer_provider:
        Optional OTel TracerProvider. If it is None and OTel is installed,
        an InMemorySpanExporter is used. If OTel is not installed, it is ignored.
    """
    
    model_config = {"arbitrary_types_allowed": True}

    api_target:      ApiTarget
    consumer_id:     str
    store:           TelemetryStore
    run_id:          str           = ""          # is populated in __init__ if it is empty
    owner:           Optional[str] = None
    repo:            Optional[str] = None
    token_hash:      Optional[str] = None
    tracer_provider: Any           = None


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class InstrumentedSession(requests.Session):
    """
    Drop-in replacement for `requests.Session`.

    For each HTTP call:
    1. Constructs an `ApiCallEvent` with full context (run_id, owner,
       repo, active context extractor, rate-limit headers).
    2. Enqueues the event in the `TelemetryStore` (does not block the caller).
    3. If OTel is available, emits a span with the same attributes.

    The extractor reads from `telemetry_context` on each call, not at
    construction time, so the same session can be used by multiple
    extractors with correct telemetry across all events.
    """

    def __init__(self, config: MiddlewareConfig) -> None:
        super().__init__()
        self._config = config

        # Generate a run_id if one has not been provided
        if not self._config.run_id:
            self._config.run_id = uuid.uuid4().hex[:12]

        # OTel — optional
        self._tracer    = None
        self._span_exporter = None

        if _OTEL_AVAILABLE:
            if config.tracer_provider is not None:
                provider = config.tracer_provider
                self._span_exporter = None
            else:
                self._span_exporter = InMemorySpanExporter()
                provider = TracerProvider()
                provider.add_span_processor(SimpleSpanProcessor(self._span_exporter))
            self._tracer = provider.get_tracer("api_digital_twin")

    # ------------------------------------------------------------------
    # Main interceptor
    # ------------------------------------------------------------------

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        endpoint_pattern = _normalise_endpoint(url, self._config.api_target)
        extractor        = get_current_extractor()

        t_start = time.perf_counter()
        ts_utc  = datetime.now(timezone.utc)

        # OTel span — only if it is available
        span = self._start_span(method, url, endpoint_pattern, extractor)

        try:
            response = super().request(method, url, **kwargs)
        except requests.RequestException as exc:
            latency_ms = (time.perf_counter() - t_start) * 1000.0
            self._finish_span(span, error=str(exc))
            self._persist_error_event(ts_utc, latency_ms, method, url,
                                      endpoint_pattern, extractor, span)
            raise

        latency_ms = (time.perf_counter() - t_start) * 1000.0

        # Extract rate-limit headers
        github_rl: Optional[GitHubRateLimitHeaders] = None
        bucket_id = "default"

        if self._config.api_target == ApiTarget.GITHUB:
            github_rl = GitHubRateLimitHeaders.from_response_headers(dict(response.headers))
            bucket_id = self._resolve_bucket(github_rl)

        # Throttling
        throttle = ThrottleSignal(
            was_throttled       = response.status_code in (429, 403),
            retry_after_seconds = self._parse_retry_after(response),
            was_cached          = response.status_code == 304,
        )

        # GraphQL Cost
        graphql_cost: Optional[GraphQLCost] = None
        if self._config.api_target == ApiTarget.GITHUB and "graphql" in url:
            graphql_cost = self._extract_graphql_cost(response)

        # Complete OTel span with response data
        self._finish_span(span, status_code=response.status_code,
                          latency_ms=latency_ms, github_rl=github_rl,
                          throttled=throttle.was_throttled)

        # Trace IDs — from OTel if available, generated otherwise
        span_id, trace_id = self._span_ids(span)

        event = ApiCallEvent(
            event_id         = span_id,
            trace_id         = trace_id,
            consumer_id      = self._config.consumer_id,
            run_id           = self._config.run_id,
            api_target       = self._config.api_target,
            # Semantic context — only available with direct integration
            owner            = self._config.owner,
            repo             = self._config.repo,
            extractor        = extractor,
            # Request
            timestamp_utc    = ts_utc,
            method           = HttpMethod(method.upper()),
            endpoint_pattern = endpoint_pattern,
            url              = url,
            # Response
            status_code      = response.status_code,
            latency_ms       = round(latency_ms, 2),
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

    def _start_span(self, method: str, url: str,
                    endpoint_pattern: str, extractor: Optional[str]) -> Any:
        if self._tracer is None:
            return None
        span = self._tracer.start_span(f"{method.upper()} {endpoint_pattern}")
        span.set_attribute("http.method",   method.upper())
        span.set_attribute("http.url",      url)
        span.set_attribute("http.target",   endpoint_pattern)
        span.set_attribute("dt.api_target", self._config.api_target.value)
        span.set_attribute("dt.run_id",     self._config.run_id)
        if self._config.owner:
            span.set_attribute("dt.owner", self._config.owner)
        if self._config.repo:
            span.set_attribute("dt.repo",  self._config.repo)
        if extractor:
            span.set_attribute("dt.extractor", extractor)
        return span

    def _finish_span(self, span: Any, *, error: Optional[str] = None,
                     status_code: int = 0, latency_ms: float = 0.0,
                     github_rl: Optional[GitHubRateLimitHeaders] = None,
                     throttled: bool = False) -> None:
        if span is None:
            return
        try:
            if error:
                span.set_status(StatusCode.ERROR, error)
            elif status_code >= 400:
                span.set_status(StatusCode.ERROR, f"HTTP {status_code}")
            else:
                span.set_status(StatusCode.OK)

            span.set_attribute("http.status_code",         status_code)
            span.set_attribute("http.response_latency_ms", round(latency_ms, 2))

            if github_rl:
                self._set_ratelimit_span_attrs(span, github_rl)
            if throttled:
                span.add_event("throttled", {"status_code": status_code})
            span.end()
        except Exception:
            pass  # OTel nunca bloquea el flujo principal

    @staticmethod
    def _span_ids(span: Any) -> tuple[str, str]:
        """Extrae span_id y trace_id de OTel, o genera UUIDs si no hay span."""
        if span is not None:
            try:
                ctx = span.get_span_context()
                if ctx.is_valid:
                    return format(ctx.span_id, "016x"), format(ctx.trace_id, "032x")
            except Exception:
                pass
        # OTel no disponible o span inválido — generar IDs propios
        return uuid.uuid4().hex[:16], uuid.uuid4().hex[:32]

    # ------------------------------------------------------------------
    # Helpers de extracción
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
            span.set_attribute("ratelimit.resource",
                rl.resource.value if hasattr(rl.resource, "value") else str(rl.resource))

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
        ts_utc: datetime,
        latency_ms: float,
        method: str,
        url: str,
        endpoint_pattern: str,
        extractor: Optional[str], span: Any) -> None:

        """A partial event persists in the event of a network error (status_code=0)."""
        span_id, trace_id = self._span_ids(span)
        try:
            self._config.store.append(ApiCallEvent(
                event_id         = span_id,
                trace_id         = trace_id,
                consumer_id      = self._config.consumer_id,
                run_id           = self._config.run_id,
                api_target       = self._config.api_target,
                owner            = self._config.owner,
                repo             = self._config.repo,
                extractor        = extractor,
                timestamp_utc    = ts_utc,
                method           = HttpMethod(method.upper()),
                endpoint_pattern = endpoint_pattern,
                url              = url,
                status_code      = 0,
                latency_ms       = round(latency_ms, 2),
                bucket_id        = "unknown",
                span_id          = span_id,
                throttle_signal  = ThrottleSignal(was_throttled=False),
            ))
        except Exception:
            pass  # Never block the caller due to telemetry errors

    # ------------------------------------------------------------------
    # Inspection (useful in tests)
    # ------------------------------------------------------------------

    @property
    def run_id(self) -> str:
        return self._config.run_id

    def get_recorded_spans(self) -> list[Any]:
        """Spans captured by the exporter in memory. Empty if OTel is not present."""
        if self._span_exporter is None:
            return []
        return self._span_exporter.get_finished_spans()