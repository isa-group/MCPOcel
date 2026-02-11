"""
Server-side cursor store for paginated tool results.

Stores full result sets from tool invocations and serves them in pages,
allowing LLMs to iterate through large result sets without exhausting context.
"""

import uuid
import math
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from shared.logger.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class CursorPage:
    """A single page of results from a cursor."""

    items: List[Any]
    page: int
    total_pages: int
    total_items: int
    cursor_id: str
    has_next: bool
    has_previous: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "items": self.items,
            "page": self.page,
            "total_pages": self.total_pages,
            "total_items": self.total_items,
            "cursor_id": self.cursor_id,
            "has_next": self.has_next,
            "has_previous": self.has_previous,
        }


@dataclass
class CursorEntry:
    """Internal entry in the cursor store."""

    cursor_id: str
    tool_name: str
    results: List[Any]
    total: int
    page_size: int
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(self.total / self.page_size))


class CursorStore:
    """
    Thread-safe server-side storage for paginated tool results.

    Results from tool invocations that exceed ``page_size`` items are stored
    here with a unique ``cursor_id``.  Subsequent calls to
    ``get_cursor_results`` retrieve additional pages without re-executing
    the query.

    Cursors expire after ``max_age_seconds`` and are garbage-collected lazily
    on every ``create_cursor`` call.
    """

    def __init__(
        self,
        default_page_size: int = 50,
        max_age_seconds: int = 300,
    ) -> None:
        self._store: Dict[str, CursorEntry] = {}
        self._lock = threading.Lock()
        self.default_page_size = default_page_size
        self.max_age_seconds = max_age_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_cursor(
        self,
        tool_name: str,
        results: List[Any],
        page_size: Optional[int] = None,
    ) -> str:
        """
        Store *results* and return a ``cursor_id``.

        Triggers lazy garbage collection of expired cursors.
        """
        self._cleanup()

        cursor_id = uuid.uuid4().hex[:12]
        ps = page_size or self.default_page_size

        entry = CursorEntry(
            cursor_id=cursor_id,
            tool_name=tool_name,
            results=results,
            total=len(results),
            page_size=ps,
        )

        with self._lock:
            self._store[cursor_id] = entry

        logger.debug(
            "Cursor created: id=%s tool=%s total=%d pages=%d",
            cursor_id,
            tool_name,
            entry.total,
            entry.total_pages,
        )
        return cursor_id

    def get_page(self, cursor_id: str, page: int = 1) -> CursorPage:
        """
        Retrieve page *page* (1-indexed) from cursor *cursor_id*.

        Raises:
            KeyError: cursor not found or expired.
            ValueError: page out of range.
        """
        with self._lock:
            entry = self._store.get(cursor_id)

        if entry is None:
            raise KeyError(
                f"Cursor '{cursor_id}' not found or expired. "
                "Please re-execute the original query."
            )

        # Check expiry
        age = (datetime.utcnow() - entry.created_at).total_seconds()
        if age > self.max_age_seconds:
            self._remove(cursor_id)
            raise KeyError(
                f"Cursor '{cursor_id}' expired after {self.max_age_seconds}s. "
                "Please re-execute the original query."
            )

        if page < 1 or page > entry.total_pages:
            raise ValueError(
                f"Page {page} out of range [1, {entry.total_pages}] "
                f"for cursor '{cursor_id}'."
            )

        start = (page - 1) * entry.page_size
        end = start + entry.page_size
        items = entry.results[start:end]

        return CursorPage(
            items=items,
            page=page,
            total_pages=entry.total_pages,
            total_items=entry.total,
            cursor_id=cursor_id,
            has_next=page < entry.total_pages,
            has_previous=page > 1,
        )

    def clear(self) -> None:
        """Remove all cursors (used during shutdown)."""
        with self._lock:
            count = len(self._store)
            self._store.clear()
        if count:
            logger.debug("Cleared %d cursors", count)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _remove(self, cursor_id: str) -> None:
        with self._lock:
            self._store.pop(cursor_id, None)

    def _cleanup(self) -> None:
        """Remove expired cursors."""
        now = datetime.now(datetime.timezone.utc)
        cutoff = timedelta(seconds=self.max_age_seconds)
        expired: List[str] = []

        with self._lock:
            for cid, entry in self._store.items():
                if (now - entry.created_at) > cutoff:
                    expired.append(cid)
            for cid in expired:
                del self._store[cid]

        if expired:
            logger.debug("Cleaned up %d expired cursors", len(expired))
