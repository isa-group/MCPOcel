import logging
import re
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Conventional Commit Parser
CC_PATTERN = re.compile(
    r"^(?P<type>\w+)"  # Type (feat, fix...)
    r"(?:\((?P<scope>[^)]+)\))?"  # Scope opcional
    r"(?P<breaking>!)?"  # Breaking change flag
    r":\s+(?P<desc>.+)$"  # Descripción
)


def parse_commit_message(message: Optional[str]) -> Dict[str, Any]:
    """
    Extract Conventional Commit info from commit message.
    Handles None and non-string inputs gracefully.
    """
    if not message or not isinstance(message, str):
        return {
            "is_conventional": False,
            "message_short": "",
            "message_full": ""
        }

    short = message.split("\n", 1)[0].strip()
    match = CC_PATTERN.match(short)

    data = {
        "message_short": short,
        "message_full": message,
        "is_conventional": bool(match)
    }

    if match:
        data.update({
            "type": match.group("type").lower(),
            "scope": match.group("scope") or "",  # Evitar None
            "breaking": bool(match.group("breaking"))
        })

    return data


# Identity Helpers
def make_id(*parts: Any) -> str:
    """
    Generate deterministic OCEL object IDs.
    Replaces spaces, slashes, and colons with underscores.
    Ignores None or empty parts.
    Raises ValueError if no valid parts provided.
    """
    valid_parts = [
        str(p).replace(" ", "_").replace("/", "_").replace(":", "")
        for p in parts if p is not None and str(p).strip() != ""
    ]

    if not valid_parts:
        raise ValueError(f"Cannot create ID from empty parts: {parts}")

    return "_".join(valid_parts)


def safe_timestamp(timestamp: Optional[str],
                   fallback: Optional[str] = None,
                   use_now: bool = False) -> str:
    """
    Return a valid ISO timestamp.

    Args:
        timestamp: Primary timestamp to use
        fallback: Fallback timestamp if primary is None
        use_now: If True, use current time as last resort

    Returns:
        Valid ISO 8601 timestamp with Z suffix
    """
    if timestamp:
        return timestamp if timestamp.endswith("Z") else f"{timestamp}Z"

    if fallback:
        return fallback if fallback.endswith("Z") else f"{fallback}Z"

    if use_now:
        return datetime.now().isoformat() + "Z"

    raise ValueError("No valid timestamp available")


def calculate_duration(start: Optional[str], end: Optional[str]) -> Optional[float]:
    """
    Calculate duration in seconds between two ISO timestamps.

    Returns:
        Duration in seconds, or None if calculation fails
    """
    if not start or not end:
        return None

    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        duration = (end_dt - start_dt).total_seconds()
        return duration if duration >= 0 else None
    except (ValueError, AttributeError) as e:
        logger.warning(f"Failed to calculate duration from {start} to {end}: {e}")
        return None


def parse_time(iso_str: Optional[str]) -> Optional[datetime]:
    """
    Parse an ISO 8601 string into a datetime object.
    Returns None if the input is invalid.
    """
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError:
        logger.warning(f"Failed to parse timestamp: {iso_str}")
        return None

