"""
Logging decorators for MCP tools.

Provides automatic DEBUG-level logging of tool invocations:
- Entry: function name + all arguments
- Exit: function name + result summary + elapsed time
"""

import time
import functools
import logging
from typing import Any, Callable, TypeVar

from .logging_config import get_logger

logger = get_logger("mcp.tools")

F = TypeVar("F", bound=Callable[..., Any])


def _summarize_result(result: Any, max_items: int = 3) -> str:
    """
    Produce a compact summary of a tool result for logging.

    Avoids dumping huge payloads into the log while still being informative.
    """
    if isinstance(result, dict):
        if "error" in result:
            return f"error={result['error']!r}"
        parts = []
        if "references" in result:
            parts.append(f"references={len(result['references'])}")
        if "total" in result:
            parts.append(f"total={result['total']}")
        if "total_items" in result:
            parts.append(f"total_items={result['total_items']}")
        if "cursor_id" in result:
            parts.append(f"cursor_id={result['cursor_id']!r}")
        if "summary" in result and isinstance(result["summary"], str):
            parts.append(f"summary_len={len(result['summary'])}")
        if "metadata" in result:
            parts.append("has_metadata=True")
        if not parts:
            parts.append(f"keys={list(result.keys())[:6]}")
        return ", ".join(parts)
    return f"type={type(result).__name__}"


def debug_log_tool(func: F) -> F:
    """
    Decorator that logs tool entry (args/kwargs) and exit (result summary + timing)
    at DEBUG level.

    Must be applied **inside** (below) ``@mcp.tool()`` so that FastMCP still
    sees the original function signature for parameter introspection::

        @mcp.tool()
        @debug_log_tool
        def my_tool(param: str) -> Dict[str, Any]:
            ...
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        tool_name = func.__name__

        if logger.isEnabledFor(logging.DEBUG):
            # Build a readable representation of the call arguments
            call_args = []
            if args:
                call_args.extend(repr(a) for a in args)
            if kwargs:
                call_args.extend(f"{k}={v!r}" for k, v in kwargs.items())
            logger.debug(
                "[TOOL CALL] %s(%s)",
                tool_name,
                ", ".join(call_args),
            )

        t0 = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - t0

            if logger.isEnabledFor(logging.DEBUG):
                summary = _summarize_result(result)
                logger.debug(
                    "[TOOL RESULT] %s -> %s (%.3fs)",
                    tool_name,
                    summary,
                    elapsed,
                )
            return result

        except Exception as exc:
            elapsed = time.perf_counter() - t0
            logger.debug(
                "[TOOL ERROR] %s raised %s: %s (%.3fs)",
                tool_name,
                type(exc).__name__,
                exc,
                elapsed,
            )
            raise

    return wrapper  # type: ignore[return-value]
