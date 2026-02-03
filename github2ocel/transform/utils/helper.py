import logging
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# 1. Structural Pattern (The "Learner"):
CC_STRUCTURAL_PATTERN = re.compile(
    r"^(?P<type>\w+)"  # Type (feat, fix...)
    r"(?:\((?P<scope>[^)]+)\))?"  # Scope opcional
    r"(?P<breaking>!)?"  # Breaking change flag
    r":\s+(?P<subject>.+)$"  # Descripción
)
# 2. Normative Set (The "Judge"): Focuses on compliance
STRICT_TYPES = {
    "feat", "fix", "docs", "style", "refactor", "perf",
    "test", "build", "ci", "chore", "revert"
}
import re
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# 1. Structural Pattern (The "Learner")
# Captures the components regardless of the type name
CC_STRUCTURAL_PATTERN = re.compile(
    r"^(?P<type>\w+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?:\s+(?P<subject>.+)$"
)

# 2. Normative Set (The "Judge")
STRICT_TYPES = {
    "feat", "fix", "docs", "style", "refactor", "perf",
    "test", "build", "ci", "chore", "revert"
}

def parse_commit_message(message: str) -> Dict[str, Any]:
    """
    Parses commit messages using a two-tier approach:
    1. Structural extraction (Flexibility)
    2. Semantic validation (Compliance)
    """
    # Defensive check: return empty structure if message is invalid
    if not message or not isinstance(message, str):
        return {
            "is_conventional": False,
            "is_strict_compliance": False,
            "commit_type": "none",
            "scope": None,
            "is_breaking": False,
            "subject": ""
        }

    first_line = message.split("\n")[0].strip()
    match = CC_STRUCTURAL_PATTERN.match(first_line)

    # Default state (Non-conventional)
    data = {
        "is_conventional": False,
        "is_strict_compliance": False,
        "commit_type": "other",
        "scope": None,
        "is_breaking": False,
        "subject": first_line # Fallback to the whole line
    }

    if match:
        groups = match.groupdict()
        data["is_conventional"] = True
        data["commit_type"] = groups["type"].lower()
        data["scope"] = groups["scope"]
        data["is_breaking"] = bool(groups["breaking"])
        data["subject"] = groups["subject"].strip()

        # Tier 2: Validation against the strict spec
        data["is_strict_compliance"] = data["commit_type"] in STRICT_TYPES

    if match and not data["is_strict_compliance"]:
        logger.debug(f"Non-standard conventional type: {data['commit_type']}")


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
    if timestamp and isinstance(timestamp, str):
        return timestamp if timestamp.endswith("Z") else f"{timestamp}Z"

    if fallback and isinstance(fallback, str):
        return fallback if fallback.endswith("Z") else f"{fallback}Z"

    if use_now:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

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

