"""
shared/telemetry/twin_runtime.py
---------------------------------
Core object of the digital twin.

Current responsibilities (Phase 1)
----------------------------------

- Open and maintain the TelemetryStore (one per process).
- Register clean shutdown with ShutdownManager.
- Construct InstrumentedSession with the correct configuration.
- Derive the semantic consumer_id.

Future responsibilities
------------------------

  Phase 2 → QuotaState, consumer profiles, token bucket model
  Phase 3 → SimPy engine, scenario runner, anomaly detector
  Phase 4 → PolicyAdvisor, MAPE-K loop, human-in-the-loop gate

The object grows here. SessionFactory remains a one-line façade.

Singleton
------------
`TwinRuntime.get()` returns the instance for the current process.
It is initialised on the first access and maintained until shutdown.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from typing import Optional

import requests

from shared.config.env import Env
from shared.logger.logging_config import get_logger

logger = get_logger(__name__)

class TwinRuntime:
    """
    Central object of the digital twin — one per process.

    Usage:
        runtime = TwinRuntime.get()
        session = runtime.create_session(token=..., owner=..., repo=...)
    """

    _instance: Optional["TwinRuntime"] = None
    _lock = threading.Lock()                    # double-checked locking para P3/P4

    def __init__(self) -> None:
        from shared.store.jsonl_store import TelemetryStore

        store_path  = Env.str("TWIN_STORE_PATH", default="data/telemetry.jsonl")
        self.store  = TelemetryStore.open(store_path)
        # run_id identifies this pipeline run in the shared store
        self.run_id = uuid.uuid4().hex[:12]

        logger.info(
            f"TwinRuntime initialised — store: {store_path}  run_id: {self.run_id}"
        )
        self._register_shutdown()

    def _register_shutdown(self) -> None:
        """
        Register store.close() with the global ShutdownManager.

        The ShutdownManager ensures that callbacks are executed only
        once (_shutdown_called flag), so there is no risk of
        a double-close during normal shutdown.

        reset() (tests only) closes the store directly and leaves the
        callback registered—store.close() is idempotent, so
        a second call from the ShutdownManager is harmless.
        """
        try:
            from shared.lifecycle import register_shutdown_callback
            register_shutdown_callback(self.store.close)
            logger.debug("TelemetryStore registered with ShutdownManager")
        except ImportError:
            pass

    # ---------------------------------------------------------------------------
    # Singleton
    # ---------------------------------------------------------------------------
    
    @classmethod
    def get(cls) -> "TwinRuntime":
        """
        Returns the process instance, creating it if this is the first time.

        Any ImportError or initialisation failure is propagated —
        it is not silently swallowed. If TWIN_ENABLED=true and the runtime
        cannot start up, this is an error that the operator must be made aware of.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:        # second check within the lock
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Destroys the current instance. Mainly used in tests."""
        with cls._lock:
            if cls._instance is not None:
                try:
                    cls._instance.store.close()
                except Exception:
                    pass
                cls._instance = None

    def create_session(
        self,
        token: Optional[str] = None,    # Optional: DBLP and other clients without a token
        owner: Optional[str] = None,
        repo:  Optional[str] = None,
    ) -> requests.Session:
        """
        Returns an InstrumentedSession configured for this runtime.

        token is Optional because not all clients have an
        authentication token (e.g., DblpClient). When present, it is used
        only to derive the audit token_hash.

        Consumer ID
        -----------
        Semantic identity: `gh:{owner}/{repo}` (or `dblp:{...}`).
        Resilient to token rotations — the token is not part of
        the identity; it is merely audit metadata.
        """
        from shared.telemetry.instrumented_session import InstrumentedSession, MiddlewareConfig
        from shared.telemetry.schema import ApiTarget

        config = MiddlewareConfig(
            api_target  = ApiTarget.GITHUB,
            consumer_id = self._derive_consumer_id(owner, repo),
            run_id      = self.run_id,
            store       = self.store,
            owner       = owner,
            repo        = repo,
            token_hash  = self._token_hash(token) if token else None,
        )

        logger.debug(f"InstrumentedSession created — consumer={config.consumer_id}")
        return InstrumentedSession(config=config)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    
    @staticmethod
    def _derive_consumer_id(owner: Optional[str], repo: Optional[str]) -> str:
        """
        Semantic identity of the consumer: `gh:{owner}/{repo}`.
        Remains stable across token rotations.
        """
        if owner and repo:
            return f"gh:{owner}/{repo}"
        return "gh:unknown"

    @staticmethod
    def _token_hash(token: str) -> str:
        """
        Short hash of the token for rotation auditing.
        Not the primary identity — it is a secondary metadata.
        """
        return hashlib.sha256(token.encode()).hexdigest()[:12]
