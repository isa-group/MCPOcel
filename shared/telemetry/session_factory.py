"""
shared/telemetry/session_factory.py
-------------------------------------
HTTP Session Factory.

Design principle
~~~~~~~~~~~~~~~~~~~
`GitHubClient` does not know whether the digital twin exists or not.
It simply calls `SessionFactory.create()` and receives a
`requests.Session` — either the instrumented version or the standard one.

The decision is made in this module, guided by the environment variable
`TWIN_ENABLED`. The client is completely unaware of it.

This ensures:
  1. `github2ocel` has no direct dependency on `digital_twin`.
  2. Enabling/disabling the twin is a change to an environment variable, not to the code.
  3. Future integration with mitmproxy (or another mechanism) only affects this file.

Enriched context
~~~~~~~~~~~~~~~~~~~~
When the twin is active, the session receives the semantic context available
at the time the client is built (owner, repo, extractor). This allows
the twin to answer questions such as:
    ‘Which extractor consumes the most quota from the core bucket?’
    ‘Which repository is closest to exhausting its search quota?’
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

import requests

from shared.config.env import Env

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Import guard: If the twin is not installed, continue
# ---------------------------------------------------------------------------

try:
    from shared.telemetry.instrumented_session import InstrumentedSession, MiddlewareConfig
    from shared.telemetry.schema import ApiTarget
    from shared.store.jsonl_store import TelemetryStore
    _TWIN_AVAILABLE = True
except ImportError:
    _TWIN_AVAILABLE = False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class SessionFactory:
    """
    HTTP session factory.

    Typical usage in `GitHubClient.__init__`:

        self.session = SessionFactory.create(
            token   = ctx.token,
            owner   = ctx.owner,
            repo    = ctx.repo,
            extractor = ‘issues’,   # optional; added by the specific extractor
        )

    The factory returns:
    - `InstrumentedSession` if `TWIN_ENABLED=true` and the store is available.
    - `requests.Session` in all other cases.

    In both cases, the `requests.Session` contract remains intact.
    """

    # Store singleton: opened once per process and shared amongst all
    # clients created during that execution.

    _store: Optional["TelemetryStore"] = None

    @classmethod
    def _get_store(cls) -> Optional["TelemetryStore"]:
        """Open the TelemetryStore for the first time; return the cached instance."""
        if not _TWIN_AVAILABLE:
            return None
        if cls._store is None:
            store_path = Env.str("TWIN_STORE_PATH", default="data/telemetry.jsonl")
            try:
                cls._store = TelemetryStore.open(store_path)
                # Registration in the global ShutdownManager for a clean shutdown
                try:
                    from shared.lifecycle import register_shutdown_callback
                    register_shutdown_callback(cls._store.close)
                    logger.debug("TelemetryStore registered with ShutdownManager")
                except ImportError:
                    pass
                logger.info(f"TelemetryStore opened at: {store_path}")
            except Exception as e:
                logger.warning(f"Could not open TelemetryStore ({e}); twin disabled")
                return None
        return cls._store

    @classmethod
    def create(
        cls,
        token:     str,
        owner:     Optional[str] = None,
        repo:      Optional[str] = None,
        extractor: Optional[str] = None,
    ) -> requests.Session:
        """
        Creates and returns an HTTP session, either instrumented or standard.

        Parameters
        ----------
        token:
            GitHub authentication token (Bearer). Used to derive the
            `consumer_id` without storing the token in plain text.
        owner:
            Repository owner (enriches telemetry).
        repo:
            Repository name (enriches telemetry).
        extractor:
            Name of the extractor requesting the session, e.g. `issues`,
            `commits`, `pull_requests`. Allows the twin to break down
            quota consumption by semantic component.
        """
        twin_enabled = Env.bool("TWIN_ENABLED", default=False)

        if not twin_enabled or not _TWIN_AVAILABLE:
            return requests.Session()

        store = cls._get_store()
        if store is None:
            return requests.Session()

        consumer_id = cls._derive_consumer_id(token, owner, repo)

        config = MiddlewareConfig(
            api_target  = ApiTarget.GITHUB,
            consumer_id = consumer_id,
            store       = store,
            owner       = owner,
            repo        = repo,
            extractor   = extractor,
        )

        logger.debug(
            f"InstrumentedSession created — consumer={consumer_id} "
            f"extractor={extractor or 'unset'}"
        )
        return InstrumentedSession(config=config)

    @staticmethod
    def _derive_consumer_id(
        token:    str,
        owner:    Optional[str],
        repo:     Optional[str],
    ) -> str:
        """
        Generate a stable, non-secret identifier for the consumer.

        Format: ``gh:{token_hash}:{owner}/{repo}``
        The hash is calculated using SHA-256 on the first 8 characters of the token,
        which allows calls from the same token to be correlated without storing it.
        """
        token_hash = hashlib.sha256(token[:8].encode()).hexdigest()[:12]
        suffix = f"{owner}/{repo}" if owner and repo else "unknown"
        return f"gh:{token_hash}:{suffix}"
