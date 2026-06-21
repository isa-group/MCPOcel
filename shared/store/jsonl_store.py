"""
shared/store/jsonl_store.py
----------------------------
Telemetry persistence: JSONL append-log + DuckDB query engine.

Write architecture — asynchronous queue
----------------------------------------
The caller (InstrumentedSession) never accesses the disk directly.
`append()` queues the event in memory and returns immediately.
A dedicated writer thread drains the queue and writes to JSONL.

    HTTP request
         ↓
    append(event)          ← O(1), non-blocking
         ↓
    queue.Queue()
         ↓                 ← separate thread
    _writer_thread
         ↓
    JSONL file

This ensures that the gem never impacts the latency of instrumented
HTTP calls, even when 100k+ events are generated.

Read architecture — DuckDB on-demand
-------------------------------------
DuckDB views are created lazily on first access following the first
write. DuckDB reads the JSONL directly from disk — there is no
external process or server.

`run_id` in queries
---------------------
All views expose `run_id`, allowing filtering by run:

    SELECT COUNT(*), AVG(latency_ms)
    FROM raw_events
    WHERE run_id = '3f1a9c'

Implementation notes
---------------------
* `_SENTINEL` is the object that the writer thread uses to detect
  clean closure — it is queued in `close()` and the thread terminates upon seeing it.
* `_ensure_typed_views()` is idempotent and safe to call multiple
  times — it resets the flag on every `append()` to re-infer the schema
  if new fields are added.
* Dot notation for DuckDB structs (`github_rate_limit.limit`) — the
  bracket notation `[“limit”]` fails because `limit` is a
  reserved word in DuckDB SQL.
"""

from __future__ import annotations

import queue
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import duckdb

from shared.telemetry.schema import ApiCallEvent, ApiTarget, BucketQuotaSnapshot


# Sentinel para señalizar al writer thread que debe terminar
_SENTINEL = object()


class TelemetryStore:
    """
    Append-only JSONL store with a DuckDB query layer.

    Typical lifecycle
    -----------------
    >>> store = TelemetryStore.open("data/telemetry.jsonl")
    >>> store.append(event)                             # called by middleware
    >>> snap = store.quota_snapshot("github", "core")   # called by analyse loop
    >>> store.close()
    """

    def __init__(self, path: Path, conn: duckdb.DuckDBPyConnection) -> None:
        self._path = path
        self._conn = conn
        self._jsonl_path = str(path.resolve())
        self._typed_views_created = False

        # Asynchronous queue — non-blocking write for the caller
        self._queue: queue.Queue = queue.Queue()
        self._writer = threading.Thread(
            target = self._writer_loop,
            name   = "telemetry-writer",
            daemon = True,   # does not prevent the proceedings from being concluded
        )
        self._writer.start()

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def open(cls, path: str | Path) -> "TelemetryStore":
        """Abre (o crea) un store en `path`."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.touch()
        conn = duckdb.connect()
        return cls(p, conn)

    # ------------------------------------------------------------------
    # Writer thread
    # ------------------------------------------------------------------

    def _writer_loop(self) -> None:
        """
        Hilo dedicado a escritura en disco.
        Drena la queue continuamente hasta recibir el sentinel de cierre.
        """
        with self._path.open("a", encoding="utf-8") as fh:
            while True:
                item = self._queue.get()
                if item is _SENTINEL:
                    fh.flush()
                    self._queue.task_done()
                    break
                try:
                    fh.write(item + "\n")
                    fh.flush()
                except Exception:
                    pass  # log en P2; nunca detener el writer por un evento corrupto
                finally:
                    self._queue.task_done()

    # ------------------------------------------------------------------
    # Flush helper
    # ------------------------------------------------------------------

    def _flush(self) -> None:
        """Espera a que todos los eventos encolados lleguen a disco."""
        self._queue.join()
        # Invalidar views para que DuckDB relea el fichero actualizado
        self._typed_views_created = False

    # ------------------------------------------------------------------
    # Public deed — O(1), does not block
    # ------------------------------------------------------------------

    def append(self, event: ApiCallEvent) -> None:
        """
        Serialises `event` and queues it for asynchronous writing.
        Returns immediately — the caller never waits for the write to disk.
        """
        self._queue.put(event.model_dump_json(exclude_none=False))
        # Disable views so that the next read infers the current schema
        self._typed_views_created = False

    # ------------------------------------------------------------------
    # Views DuckDB — creación lazy
    # ------------------------------------------------------------------

    def _ensure_typed_views(self) -> bool:
        """
        Creates the DuckDB views if the file contains data.
        Returns True if the views are ready, False if the file is empty.
        Idempotent.
        """
        if self._typed_views_created:
            return True
        if self._path.stat().st_size == 0:
            return False

        jp = self._jsonl_path

        try:
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
                    run_id,
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

            # run_stats: cost per execution — the query that run_id enables
            self._conn.execute("""
                CREATE OR REPLACE VIEW run_stats AS
                SELECT
                    run_id,
                    consumer_id,
                    owner,
                    repo,
                    MIN(timestamp_utc)  AS started_at,
                    MAX(timestamp_utc)  AS ended_at,
                    COUNT(*)            AS total_calls,
                    AVG(latency_ms)     AS avg_latency_ms,
                    MAX(latency_ms)     AS max_latency_ms,
                    SUM(CASE WHEN throttle_signal.was_throttled THEN 1 ELSE 0 END)
                                        AS throttled_calls,
                    COUNT(DISTINCT extractor) AS extractors_used
                FROM raw_events
                GROUP BY run_id, consumer_id, owner, repo
            """)

            # recent_call_rate: calls/min per (bucket, consumer) over last 10 min
            self._conn.execute("""
                CREATE OR REPLACE VIEW recent_call_rate AS
                SELECT
                    api_target,
                    bucket_id,
                    consumer_id,
                    run_id,
                    COUNT(*)        AS calls_last_10min,
                    COUNT(*) / 10.0 AS calls_per_minute
                FROM raw_events
                WHERE TRY_CAST(timestamp_utc AS TIMESTAMPTZ) >= NOW() - INTERVAL 10 MINUTE
                GROUP BY api_target, bucket_id, consumer_id, run_id
            """)

            # throttle_events: all calls that were rate-limited
            self._conn.execute("""
                CREATE OR REPLACE VIEW throttle_events AS
                SELECT
                    timestamp_utc,
                    api_target,
                    bucket_id,
                    consumer_id,
                    run_id,
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
        api_target:  str,
        bucket_id:   str,
        consumer_id: Optional[str] = None,
    ) -> Optional[BucketQuotaSnapshot]:
        """Return the latest known quota state for (api_target, bucket_id, consumer_id)."""
        self._flush()
        if not self._ensure_typed_views():
            return None

        try:
            if consumer_id:
                rows = self._conn.execute(
                    """SELECT api_target, bucket_id, consumer_id,
                              rl_limit, rl_remaining, rl_used, rl_reset_unix, last_seen
                       FROM latest_quota
                       WHERE api_target = ? AND bucket_id = ? AND consumer_id = ?""",
                    [api_target, bucket_id, consumer_id],
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """SELECT api_target, bucket_id, consumer_id,
                              rl_limit, rl_remaining, rl_used, rl_reset_unix, last_seen
                       FROM latest_quota
                       WHERE api_target = ? AND bucket_id = ?
                       ORDER BY last_seen DESC LIMIT 1""",
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
        self._flush()
        if not self._ensure_typed_views():
            return []
        try:
            rows = self._conn.execute(
                """SELECT api_target, bucket_id, consumer_id,
                          rl_limit, rl_remaining, rl_used, rl_reset_unix, last_seen
                   FROM latest_quota ORDER BY api_target, bucket_id"""
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

    def run_summary(self, run_id: str) -> Optional[dict[str, Any]]:
        """
        Resumen de coste de una ejecución concreta.

        Responde: "¿cuántas llamadas hizo esta ejecución?
                   ¿cuánto tardó de media? ¿cuántos throttles tuvo?"
        """
        self._flush()
        if not self._ensure_typed_views():
            return None
        try:
            rows = self._conn.execute(
                "SELECT * FROM run_stats WHERE run_id = ?", [run_id]
            ).fetchall()
            if not rows:
                return None
            cols = [d[0] for d in self._conn.description]
            return dict(zip(cols, rows[0]))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Diagnostics & raw SQL access
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return total number of events persisted"""
        self._flush()
        if not self._ensure_typed_views():
            return 0
        try:
            return self._conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
        except Exception:
            return 0

    def tail(self, n: int = 10) -> list[dict[str, Any]]:
        """Return the last `n` events as dicts (useful for debugging)."""
        self._flush()
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
        """xecute an arbitrary SQL query against the telemetry views."""
        self._flush()
        self._ensure_typed_views()
        return self._conn.execute(query).fetchall()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Drain the queue, wait for the writer thread, and close the DuckDB connection."""
        if not self._writer.is_alive():
            return
        self._queue.put(_SENTINEL)
        self._writer.join(timeout=10)
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self) -> "TelemetryStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()