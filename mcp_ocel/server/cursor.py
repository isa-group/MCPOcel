"""
Server-side cursor store for tool results.

Stores full result sets from tool invocations, allowing LLMs to reason
about subsets without materialising data into context until explicitly
requested via ``get_cursor_data``.
Cursors persist for the full lifetime of the MCP lifespan.
They are cleared on server shutdown via ``clear()``.
"""

import uuid
import threading
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from shared.logger.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class CursorEntry:
    """Internal entry in the cursor store."""

    cursor_id: str
    tool_name: str
    results: List[Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def activity_types(self) -> Optional[List[str]]:
        if not self.results or not isinstance(self.results[0], dict) or "activity" not in self.results[0]:
            return None
        activities: set = set()
        for item in self.results:
            act = item.get("activity")
            if act:
                activities.add(act)
        return sorted(activities)

    @property
    def object_types(self) -> Optional[List[str]]:
        if not self.results or not isinstance(self.results[0], dict) or "activity" not in self.results[0]:
            return None
        obj_types: set = set()
        for item in self.results:
            for obj in item.get("involved_objects", []):
                ot = obj.get("object_type")
                if ot:
                    obj_types.add(ot)
        return sorted(obj_types)

    @property
    def time_start(self) -> Optional[str]:
        if not self.results or not isinstance(self.results[0], dict) or "activity" not in self.results[0]:
            return None
        timestamps = [str(item["timestamp"]) for item in self.results if item.get("timestamp")]
        return min(timestamps) if timestamps else None

    @property
    def time_end(self) -> Optional[str]:
        if not self.results or not isinstance(self.results[0], dict) or "activity" not in self.results[0]:
            return None
        timestamps = [str(item["timestamp"]) for item in self.results if item.get("timestamp")]
        return max(timestamps) if timestamps else None


class CursorStore:
    """
    Thread-safe server-side storage for paginated tool results.

    Results from tool invocations that produce lists are stored here with a
    unique ``cursor_id``. Cursors persist for the full lifetime of the MCP
    session — there is no TTL. They are cleared when the server shuts down
    via ``clear()``.
    """

    def __init__(self) -> None:
        self._store: Dict[str, CursorEntry] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_cursor(
        self,
        tool_name: str,
        results: List[Any],
    ) -> str:
        """
        Store *results* and return a ``cursor_id``.
        """
        cursor_id = uuid.uuid4().hex[:12]

        entry = CursorEntry(
            cursor_id=cursor_id,
            tool_name=tool_name,
            results=results,
        )

        with self._lock:
            self._store[cursor_id] = entry

        logger.debug(
            "Cursor created: id=%s tool=%s total=%d",
            cursor_id,
            tool_name,
            entry.total,
        )
        return cursor_id

    def get_all_items(self, cursor_id: str) -> List[Any]:
        """
        Retrieve **all** items stored in a cursor (unpaginated).

        Used internally by the tool-chaining mechanism so that a downstream
        tool can operate on the full result set produced by an upstream tool.

        Args:
            cursor_id: The cursor identifier.

        Returns:
            The complete list of items stored in the cursor.

        Raises:
            KeyError: cursor not found.
        """
        with self._lock:
            entry = self._store.get(cursor_id)

        if entry is None:
            raise KeyError(
                f"Cursor '{cursor_id}' not found. "
                "Please re-execute the original query."
            )

        return list(entry.results)

    def get_total(self, cursor_id: str) -> int:
        """
        Return the total number of items stored in a cursor.

        Raises:
            KeyError: cursor not found.
        """
        with self._lock:
            entry = self._store.get(cursor_id)

        if entry is None:
            raise KeyError(f"Cursor '{cursor_id}' not found.")

        return entry.total

    def get_timerange(self, cursor_id: str) -> Dict[str, Any]:
        """
        Return the temporal range of items in a cursor.

        Only available when the cursor was created from event-reference items
        (items with a ``timestamp`` field).

        Returns:
            Dict with ``start``, ``end``, ``duration_seconds``.

        Raises:
            KeyError: cursor not found.
            ValueError: cursor contains no timestamp data.
        """
        with self._lock:
            entry = self._store.get(cursor_id)

        if entry is None:
            raise KeyError(f"Cursor '{cursor_id}' not found.")

        if entry.time_start is None or entry.time_end is None:
            raise ValueError(
                f"Cursor '{cursor_id}' has no timestamp data. "
                "This cursor may not contain event references."
            )

        duration_seconds: Optional[float] = None
        try:
            start_dt = datetime.fromisoformat(
                entry.time_start.replace("Z", "+00:00")
            )
            end_dt = datetime.fromisoformat(
                entry.time_end.replace("Z", "+00:00")
            )
            duration_seconds = (end_dt - start_dt).total_seconds()
        except Exception:
            pass

        return {
            "start": entry.time_start,
            "end": entry.time_end,
            "duration_seconds": duration_seconds,
        }

    def get_summary(self, cursor_id: str) -> Dict[str, Any]:
        """
        Return a lightweight summary of the cursor contents.

        ``activity_types``, ``object_types``, and time range fields are
        populated only when the cursor was created from event-reference items.

        Returns:
            Dict with ``total``, ``activity_types``, ``object_types``,
            ``time_start``, ``time_end``.

        Raises:
            KeyError: cursor not found.
        """
        with self._lock:
            entry = self._store.get(cursor_id)

        if entry is None:
            raise KeyError(f"Cursor '{cursor_id}' not found.")

        return {
            "total": entry.total,
            "activity_types": entry.activity_types,
            "object_types": entry.object_types,
            "time_start": entry.time_start,
            "time_end": entry.time_end,
        }

    def clear(self) -> None:
        """Remove all cursors (used during shutdown)."""
        with self._lock:
            count = len(self._store)
            self._store.clear()
        if count:
            logger.debug("Cleared %d cursors", count)
