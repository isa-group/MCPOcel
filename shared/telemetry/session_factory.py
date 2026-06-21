"""
shared/telemetry/session_factory.py
-------------------------------------
The only decision this module makes is:
  - `TWIN_ENABLED=false` → standard `requests.Session()`
  - `TWIN_ENABLED=true`  → `TwinRuntime.get().create_session(...)`

Behaviour on errors when TWIN_ENABLED=true
---------------------------------------------
If `TwinRuntime` cannot be imported or initialised, the error is
propagated — there is NO silent fallback to `requests.Session()`.

Reason: if an operator sets `TWIN_ENABLED=true`, they expect telemetry.
Losing it silently is worse than a visible failure. An `ImportError`
here indicates a bug in the code or a deployment error — both of which must
be immediately visible.

Extractor
-------------
The extractor is NOT passed during session construction. It is propagated via
`contextvars` in each HTTP call:

    from shared.telemetry.session_factory import telemetry_context

    with telemetry_context(extractor=‘issues’):
        client.rest(‘/repos/{owner}/{repo}/issues’)
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Generator, Optional

import requests

from shared.config.env import Env

# ContextVar that propagates the active extractor to every HTTP call
_current_extractor: ContextVar[Optional[str]] = ContextVar(
    "_current_extractor", default=None
)


@contextmanager
def telemetry_context(extractor: str) -> Generator[None, None, None]:
    """
    The context manager propagates the active extractor to the telemetry.

    Usage:
        with telemetry_context(extractor="issues"):
            for page in client.rest_paginated("/repos/.../issues"):
                ...

    Any HTTP call within the block will have
    `extractor="issues"` in its `ApiCallEvent`.

    If `TWIN_ENABLED=false`, this context manager is a no-op
    with virtually zero overhead.
    """
    token = _current_extractor.set(extractor)
    try:
        yield
    finally:
        _current_extractor.reset(token)


def get_current_extractor() -> Optional[str]:
    """Returns the active extractor in the current context, or None."""
    return _current_extractor.get()


class SessionFactory:
    """
    Minimal front-end on top of TwinRuntime.

    All the actual logic resides in TwinRuntime. This module simply decides
    whether or not to invoke it, depending on TWIN_ENABLED.

    Usage in GitHubClient.__init__:

        self.session = SessionFactory.create(
            token = ctx.token,
            owner = ctx.owner,
            repo  = ctx.repo,
    """

    @classmethod
    def create(
        cls,
        token: str,
        owner: Optional[str] = None,
        repo:  Optional[str] = None,
    ) -> requests.Session:
        """
        Returns an InstrumentedSession if TWIN_ENABLED=true,
        or requests.Session() if TWIN_ENABLED=false.

        When TWIN_ENABLED=true, any import or
        initialisation errors are propagated to the caller — they are never
        silently suppressed.
        """
        if not Env.bool("TWIN_ENABLED", default=False):
            return requests.Session()

        # Direct import — no try/except.
        # If it fails with TWIN_ENABLED=true, the error should be visible.
        from shared.telemetry.twin_runtime import TwinRuntime

        return TwinRuntime.get().create_session(
            token = token,
            owner = owner,
            repo  = repo,
        )