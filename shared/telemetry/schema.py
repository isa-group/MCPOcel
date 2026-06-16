"""
shared/telemetry/schema.py
--------------------------
Pydantic v2 models for each telemetry event captured by the middleware.

Design
~~~~~~
* Each HTTP interaction produces exactly one `ApiCallEvent`.
* The `extractor` field identifies which github2ocel component generated the
  call (issues, commits, pull_requests, …), enabling queries such as
  “which extractor consumes the most quota?” — information impossible to obtain with
  an external proxy.
* `GitHubRateLimitHeaders` parses the X-RateLimit-* headers directly
  from the response dict (case-insensitive).
* DBLP has no structured headers; throttling is inferred in Phase 2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ApiTarget(str, Enum):
    GITHUB = "github"
    DBLP   = "dblp"


class HttpMethod(str, Enum):
    GET    = "GET"
    POST   = "POST"
    PUT    = "PUT"
    PATCH  = "PATCH"
    DELETE = "DELETE"
    HEAD   = "HEAD"


class GitHubBucket(str, Enum):
    """Known rate-limit buckets in the GitHub REST API."""
    CORE                         = "core"
    SEARCH                       = "search"
    GRAPHQL                      = "graphql"
    CODE_SEARCH                  = "code_search"
    ACTIONS_RUNNER_REGISTRATION  = "actions_runner_registration"
    SCIM                         = "scim"
    DEPENDENCY_SNAPSHOTS         = "dependency_snapshots"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class GitHubRateLimitHeaders(BaseModel):
    """
    Parsed values from the X-RateLimit-* family of headers returned by GitHub.

    Reference:
        X-RateLimit-Limit      → maximum quota of the current bucket
        X-RateLimit-Remaining  → remaining tokens until reset
        X-RateLimit-Reset      → Unix timestamp of the next reset
        X-RateLimit-Used       → tokens used since the last reset
        X-RateLimit-Resource   → bucket name (core, search, graphql, …)
        Retry-After            → wait time in seconds (only for 429 / 403 secondary)
    """
    limit:               Optional[int]                    = Field(None)
    remaining:           Optional[int]                    = Field(None)
    reset_unix:          Optional[int]                    = Field(None)
    used:                Optional[int]                    = Field(None)
    resource:            Optional[GitHubBucket | str]     = Field(None)
    github_request_id:   Optional[str]                    = Field(None)
    retry_after_seconds: Optional[int]                    = Field(None)

    @property
    def reset_at(self) -> Optional[datetime]:
        if self.reset_unix is None:
            return None
        return datetime.fromtimestamp(self.reset_unix, tz=timezone.utc)

    @property
    def consumption_ratio(self) -> Optional[float]:
        if self.used is not None and self.limit:
            return self.used / self.limit
        if self.remaining is not None and self.limit:
            return (self.limit - self.remaining) / self.limit
        return None

    @classmethod
    def from_response_headers(cls, headers: dict[str, str]) -> "GitHubRateLimitHeaders":
        """Factory: constructs the model from the header dict (case-insensitive)."""
        h = {k.lower(): v for k, v in headers.items()}

        def _int(key: str) -> Optional[int]:
            try:
                return int(h[key])
            except (KeyError, ValueError, TypeError):
                return None

        resource_raw = h.get("x-ratelimit-resource")
        resource: Optional[GitHubBucket | str] = None
        if resource_raw:
            try:
                resource = GitHubBucket(resource_raw.lower())
            except ValueError:
                resource = resource_raw

        return cls(
            limit               = _int("x-ratelimit-limit"),
            remaining           = _int("x-ratelimit-remaining"),
            reset_unix          = _int("x-ratelimit-reset"),
            used                = _int("x-ratelimit-used"),
            resource            = resource,
            github_request_id   = h.get("x-github-request-id"),
            retry_after_seconds = _int("retry-after"),
        )


class ThrottleSignal(BaseModel):
    """Observable throttling signals for any API."""
    was_throttled:       bool         = False
    retry_after_seconds: Optional[int] = None
    was_cached:          bool         = False


class GraphQLCost(BaseModel):
    """Cost in points of a GitHub GraphQL query (extracted from the body)."""
    points_consumed: Optional[int] = None
    points_limit:    Optional[int] = None


# ---------------------------------------------------------------------------
# Evento principal
# ---------------------------------------------------------------------------

class ApiCallEvent(BaseModel):
    """
    Telemetry unit: one event per HTTP call made.

    The ``extractor`` field is the key contribution of the direct integration
    over the proxy: it identifies the github2ocel component that
    originated the call, allowing quota consumption to be grouped by extractor.
    """

    # Identity and traceability
    event_id:   str = Field(description="Unique event ID (span ID OTel, hex)")
    trace_id:   str = Field(description="OTel Trace ID — links spans from the same execution")
    consumer_id: str = Field(description="Consumer process ID (derived from token, owner, repo)")
    api_target: ApiTarget

    # Semantic context — only available with direct integration
    owner:     Optional[str] = Field(None, description="GitHub repository owner")
    repo:      Optional[str] = Field(None, description="GitHub repository name")
    extractor: Optional[str] = Field(
        None,
        description=(
            "github2ocel component that originated the call "
            "(issues, commits, pull_requests, releases, …). "
            "None for calls from DBLP or other clients."
        ),
    )

    # Request
    timestamp_utc:    datetime
    method:           HttpMethod
    endpoint_pattern: str = Field(
        description="Standardised URL with placeholders, e.g.  '/repos/{owner}/{repo}/issues'"
    )
    url: str = Field(description="Complete URL as sent (only for debugging)")

    # Response
    status_code: int
    latency_ms:  float = Field(ge=0.0)

    # Rate-limit signals
    github_rate_limit: Optional[GitHubRateLimitHeaders] = None
    throttle_signal:   ThrottleSignal                   = Field(default_factory=ThrottleSignal)
    graphql_cost:      Optional[GraphQLCost]            = None

    # Affected rate-limit bucket
    bucket_id: str = Field(
        description=(
            "Bucket used by this call."
            "GitHub: value of X-RateLimit-Resource (“core”, “search”, “graphql')"
            "DBLP: always “default” until Phase 2 defines sub-buckets."
        )
    )

    # Link OTel
    span_id:        str
    parent_span_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("timestamp_utc", mode="before")
    @classmethod
    def _ensure_utc(cls, v: object) -> datetime:
        if isinstance(v, str):
            v = datetime.fromisoformat(v)
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v  # type: ignore[return-value]

    @model_validator(mode="after")
    def _infer_throttle_from_status(self) -> "ApiCallEvent":
        if self.status_code == 429:
            self.throttle_signal.was_throttled = True
        if self.status_code == 304:
            self.throttle_signal.was_cached = True
        return self

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def tokens_remaining(self) -> Optional[int]:
        return self.github_rate_limit.remaining if self.github_rate_limit else None

    @property
    def quota_exhausted(self) -> bool:
        return self.tokens_remaining == 0 or self.throttle_signal.was_throttled


# ---------------------------------------------------------------------------
# Quota snapshot (derived state; not persisted directly)
# ---------------------------------------------------------------------------

class BucketQuotaSnapshot(BaseModel):
    """
    Current quota status for a specific rate-limit bucket.
    This is calculated on-demand by querying the most recent ApiCallEvents in DuckDB.
    """
    api_target:   ApiTarget
    bucket_id:    str
    limit:        Optional[int]      = None
    remaining:    Optional[int]      = None
    used:         Optional[int]      = None
    reset_at:     Optional[datetime] = None
    last_updated: datetime           = Field(default_factory=lambda: datetime.now(timezone.utc))
    consumer_id:  Optional[str]      = None

    @property
    def seconds_until_reset(self) -> Optional[float]:
        if self.reset_at is None:
            return None
        return max(0.0, (self.reset_at - datetime.now(timezone.utc)).total_seconds())

    @property
    def depletion_fraction(self) -> Optional[float]:
        if self.used is not None and self.limit:
            return self.used / self.limit
        if self.remaining is not None and self.limit:
            return (self.limit - self.remaining) / self.limit
        return None
