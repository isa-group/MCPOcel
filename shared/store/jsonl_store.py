"""
store/jsonl_store.py
--------------------
Telemetry persistence layer: JSONL append-log + DuckDB query engine.

Architecture (Option 1 from the design document)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Every ``ApiCallEvent`` is serialised as one JSON line and appended to a
  ``.jsonl`` file.  This is the write path: O(1), no locking issues.
* DuckDB reads the JSONL file on-demand using ``read_json_auto()``.
  Negligible latency for the call volumes expected in a research project.
* On restart, the store re-opens the existing file — no rebuild needed.

Why JSONL and not Parquet?
  Parquet is immutable: appending requires rewriting the file.  JSONL is
  append-only and human-readable, which simplifies debugging.  DuckDB can
  still query it with full SQL.  A periodic compaction job (Phase 2) will
  convert accumulated JSONL to Parquet for long-term storage efficiency.

DuckDB view strategy
~~~~~~~~~~~~~~~~~~~~
  DuckDB cannot infer schema from an empty JSONL file, so the typed views
  (github_rate_limit, latest_quota, etc.) are created LAZILY on first
  access rather than at open time.  ``_ensure_typed_views()`` is idempotent
  and called before every query that needs the typed views.

DuckDB struct field access
~~~~~~~~~~~~~~~~~~~~~~~~~~
  Pydantic serialises nested models as JSON objects; DuckDB infers them as
  STRUCT types.  The correct access syntax is dot-notation:
      github_rate_limit.remaining
  NOT bracket notation, because ``limit`` is a reserved word in DuckDB SQL
  and bracket notation (`github_rate_limit['limit']`) triggers a parser error.
  Dot notation bypasses the reserved-word ambiguity correctly.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from shared.telemetry.schema import ApiCallEvent, ApiTarget, BucketQuotaSnapshot


class TelemetryStore:
    """
    Append-only JSONL store with a DuckDB query layer.

    Typical lifecycle
    -----------------
    >>> store = TelemetryStore.open("telemetry.jsonl")
    >>> store.append(event)                              # called by middleware
    >>> snap = store.quota_snapshot("github", "core")   # called by analyse loop
    >>> store.close()
    """

    def __init__(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        self._path = path
        self._conn = conn
        self._lock = threading.Lock()
        self._fh = path.open("a", encoding="utf-8")
        self._jsonl_path = str(path.resolve())
        self._typed_views_created = False

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def open(cls, path: str | Path) -> "TelemetryStore":
        """Open (or create) a telemetry store at ``path``."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.touch()
        conn = duckdb.connect()
        return cls(p, conn)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, event: ApiCallEvent) -> None:
        """Serialise ``event`` and append it to the JSONL file."""
        line = event.model_dump_json(exclude_none=False) + "\n"
        with self._lock:
            self._fh.write(line)
            self._fh.flush()
        # Mark views stale so the next read picks up the new schema if needed
        self._typed_views_created = False

    # ------------------------------------------------------------------
    # Lazy view management
    # ------------------------------------------------------------------

    def _ensure_typed_views(self) -> bool:
        """
        Create (or refresh) DuckDB views over the JSONL file.

        Returns True if views are ready to query, False if the file is still
        empty (no events persisted yet).  Idempotent.

        Struct field access uses dot notation (``github_rate_limit.remaining``)
        rather than bracket notation because ``limit`` is a reserved word in
        DuckDB and ``['limit']`` causes a parser error.
        """
        if self._typed_views_created:
            return True

        # DuckDB cannot infer schema from an empty file — skip until data arrives
        if self._path.stat().st_size == 0:
            return False

        jp = self._jsonl_path

        try:
            # raw_events: full event stream, schema inferred from JSONL
            self._conn.execute(
                f"CREATE OR REPLACE VIEW raw_events AS "
                f"SELECT * FROM read_json_auto('{jp}', ignore_errors=true)"
            )
        except Exception:
            return False

        try:
            # github_rate_limit: one row per GitHub call that carried RL headers.
            # Dot notation for struct fields — avoids the 'limit' reserved-word issue.
            self._conn.execute("""
                CREATE OR REPLACE VIEW github_rate_limit AS
                SELECT
                    timestamp_utc,
                    api_target,
                    consumer_id,
                    bucket_id,
                    status_code,
                    latency_ms,
                    github_rate_limit.limit             AS rl_limit,
                    github_rate_limit.remaining         AS rl_remaining,
                    github_rate_limit.used              AS rl_used,
                    github_rate_limit.reset_unix        AS rl_reset_unix,
                    throttle_signal.was_throttled       AS was_throttled,
                    throttle_signal.retry_after_seconds AS retry_after
                FROM raw_events
                WHERE api_target = 'github'
                  AND github_rate_limit IS NOT NULL
            """)

            # latest_quota: most recent quota state per (api_target, bucket, consumer)
            self._conn.execute("""
                CREATE OR REPLACE VIEW latest_quota AS
                SELECT
                    api_target,
                    bucket_id,
                    consumer_id,
                    LAST(rl_limit      ORDER BY timestamp_utc) AS rl_limit,
                    LAST(rl_remaining  ORDER BY timestamp_utc) AS rl_remaining,
                    LAST(rl_used       ORDER BY timestamp_utc) AS rl_used,
                    LAST(rl_reset_unix ORDER BY timestamp_utc) AS rl_reset_unix,
                    MAX(timestamp_utc)                         AS last_seen
                FROM github_rate_limit
                GROUP BY api_target, bucket_id, consumer_id
            """)

            # recent_call_rate: calls/min per (bucket, consumer) over last 10 min
            self._conn.execute("""
                CREATE OR REPLACE VIEW recent_call_rate AS
                SELECT
                    api_target,
                    bucket_id,
                    consumer_id,
                    COUNT(*)        AS calls_last_10min,
                    COUNT(*) / 10.0 AS calls_per_minute
                FROM raw_events
                WHERE TRY_CAST(timestamp_utc AS TIMESTAMPTZ) >= NOW() - INTERVAL 10 MINUTE
                GROUP BY api_target, bucket_id, consumer_id
            """)

            # throttle_events: all calls that were rate-limited
            self._conn.execute("""
                CREATE OR REPLACE VIEW throttle_events AS
                SELECT
                    timestamp_utc,
                    api_target,
                    bucket_id,
                    consumer_id,
                    status_code,
                    throttle_signal.retry_after_seconds AS retry_after
                FROM raw_events
                WHERE throttle_signal.was_throttled = true
            """)

        except Exception:
            # Views will be retried on the next call
            return False

        self._typed_views_created = True
        return True

    # ------------------------------------------------------------------
    # Quota state queries (on-demand — no in-memory state object needed)
    # ------------------------------------------------------------------

    def quota_snapshot(
        self,
        api_target: str,
        bucket_id: str,
        consumer_id: str | None = None,
    ) -> BucketQuotaSnapshot | None:
        """
        Return the latest known quota state for (api_target, bucket_id).
        Returns None if no data exists yet for this bucket.
        """
        if not self._ensure_typed_views():
            return None

        try:
            if consumer_id:
                rows = self._conn.execute(
                    """
                    SELECT api_target, bucket_id, consumer_id,
                           rl_limit, rl_remaining, rl_used, rl_reset_unix, last_seen
                    FROM latest_quota
                    WHERE api_target = ? AND bucket_id = ? AND consumer_id = ?
                    """,
                    [api_target, bucket_id, consumer_id],
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT api_target, bucket_id, consumer_id,
                           rl_limit, rl_remaining, rl_used, rl_reset_unix, last_seen
                    FROM latest_quota
                    WHERE api_target = ? AND bucket_id = ?
                    ORDER BY last_seen DESC
                    LIMIT 1
                    """,
                    [api_target, bucket_id],
                ).fetchall()
        except Exception:
            return None

        if not rows:
            return None

        _, _, cid, limit, remaining, used, reset_unix, last_seen = rows[0]

        reset_at = (
            datetime.fromtimestamp(reset_unix, tz=timezone.utc)
            if reset_unix is not None
            else None
        )

        return BucketQuotaSnapshot(
            api_target=ApiTarget(api_target),
            bucket_id=bucket_id,
            limit=limit,
            remaining=remaining,
            used=used,
            reset_at=reset_at,
            last_updated=(
                last_seen if isinstance(last_seen, datetime)
                else datetime.now(timezone.utc)
            ),
            consumer_id=cid,
        )

    def all_bucket_snapshots(self) -> list[BucketQuotaSnapshot]:
        """Return the latest quota state for every known bucket."""
        if not self._ensure_typed_views():
            return []

        try:
            rows = self._conn.execute(
                """
                SELECT api_target, bucket_id, consumer_id,
                       rl_limit, rl_remaining, rl_used, rl_reset_unix, last_seen
                FROM latest_quota
                ORDER BY api_target, bucket_id
                """
            ).fetchall()
        except Exception:
            return []

        result = []
        for api_target, bucket_id, cid, limit, remaining, used, reset_unix, last_seen in rows:
            reset_at = (
                datetime.fromtimestamp(reset_unix, tz=timezone.utc)
                if reset_unix is not None
                else None
            )
            result.append(
                BucketQuotaSnapshot(
                    api_target=ApiTarget(api_target),
                    bucket_id=bucket_id,
                    limit=limit,
                    remaining=remaining,
                    used=used,
                    reset_at=reset_at,
                    last_updated=(
                        last_seen if isinstance(last_seen, datetime)
                        else datetime.now(timezone.utc)
                    ),
                    consumer_id=cid,
                )
            )
        return result

    # ------------------------------------------------------------------
    # Diagnostics & raw SQL access
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return total number of events persisted."""
        if not self._ensure_typed_views():
            return 0
        try:
            return self._conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
        except Exception:
            return 0

    def tail(self, n: int = 10) -> list[dict[str, Any]]:
        """Return the last ``n`` events as dicts (useful for debugging)."""
        if not self._ensure_typed_views():
            return []
        try:
            rows = self._conn.execute(
                f"SELECT * FROM raw_events ORDER BY timestamp_utc DESC LIMIT {n}"
            ).fetchall()
            cols = [d[0] for d in self._conn.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            return []

    def sql(self, query: str) -> list[tuple]:
        """Execute an arbitrary SQL query against the telemetry views."""
        self._ensure_typed_views()
        return self._conn.execute(query).fetchall()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._fh.close()
        self._conn.close()

    def __enter__(self) -> "TelemetryStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
