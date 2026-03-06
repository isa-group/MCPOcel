import re
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from shared.ocel.builder import OCELBuilder
from shared.ocel.model.models  import Event
from shared.logger import get_logger

logger = get_logger(__name__)

# 1. Structural Pattern (The "Learner")
# Captures the components regardless of the type name
CC_STRUCTURAL_PATTERN = re.compile(
    r"^(?P<type>\w+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?:\s+(?P<subject>.+)$"
)

ISSUE_REF_PATTERN = re.compile(r"(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)?\s*#(\d+)", re.IGNORECASE)

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
            "is_conventional": 0,
            "commit_type": "unknown",
            "scope": None,
            "is_breaking": 0,
            "subject": "",
            "body": "",
            "full_message": "",
            "issue_refs": []
        }

    lines = message.strip().split('\n', 1)
    header = lines[0].strip()
    body = lines[1].strip() if len(lines) > 1 else ""

    # Conventional Commit
    match = CC_STRUCTURAL_PATTERN.match(header)

    # Default state (Non-conventional)
    data = {
        "full_message": message,
        "subject": header,
        "body": body,
        "body_length": len(body),
        "is_conventional": 0,
        "commit_type": "other",
        "scope": None, # Null (SQLite)
        "is_breaking": 0,
        "issue_refs": []# Fallback to the whole line
    }

    if match:
        groups = match.groupdict()
        data["is_conventional"] = 1
        data["commit_type"] = groups["type"].lower()
        data["scope"] = groups["scope"]
        # Detect breaking changes by ‘!’ or by text in the body
        data["is_breaking"] = 1 if groups["breaking"] or "BREAKING CHANGE" in body else 0
        data["subject"] = groups["subject"].strip()

    refs = ISSUE_REF_PATTERN.findall(message)
    if refs:
        # refs can be a list of tuples or strings
        clean_refs = []
        for r in refs:
            val = r if isinstance(r, str) else r[-1]
            if val.isdigit():
                clean_refs.append(val)
        data["issue_refs"] = list(set(clean_refs)) # Unique

    return data

# Identity & Time Helpers
def make_id(repo_id: str, entity_type: str, raw_id: Any) -> str:
    """
    Generate deterministic OCEL object IDs: repo_type_id
    Example: facebook_react_issue_123
    """
    if raw_id is None or str(raw_id).strip() == "":
        raise ValueError(f"Cannot create ID for {entity_type} with empty raw_id")

    # Clean parts to be filesystem/url safe just in case
    clean_repo = str(repo_id).strip().replace(" ", "_").replace("/", "_")
    clean_type = str(entity_type).strip().lower()
    clean_id = str(raw_id).strip().replace(" ", "_").replace(":", "")

    return f"{clean_repo}_{clean_type}_{clean_id}"

def safe_timestamp(timestamp: Optional[str],
                   fallback: Optional[str] = None,
                   use_now: bool = False) -> str:
    """Returns ISO 8601 string with Z suffix."""

    val = timestamp or fallback

    if val and isinstance(val, str):
        # Fix common github format nuances if any
        return val if val.endswith("Z") else f"{val}Z"

    if use_now:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Last resort to prevent crashes, epoch start
    return "1970-01-01T00:00:00Z"

def calculate_duration(start: Optional[str], end: Optional[str]) -> Optional[float]:
    """
    Calculate duration in seconds between two ISO timestamps.
    Returns: Duration in seconds, or None if calculation fails.
    """
    if not start or not end:
        return None

    try:
        # Normalize Z to +00:00 for fromisoformat compatibility
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))

        duration = (end_dt - start_dt).total_seconds()

        # Return 0 if negative (clock skew protection), otherwise duration
        return max(0.0, duration)

    except (ValueError, AttributeError) as e:
        logger.debug(f"Failed to calculate duration from {start} to {end}: {e}")
        return None

# Regex semver oficial (simplificada)
SEMVER_PATTERN = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?:-(?P<prerelease>[0-9A-Za-z-]+))?(\+[0-9A-Za-z-]+)?$"
)

def parse_semver(tag_name: str) -> Dict[str, Any]:
    """
    Desglosa un tag v1.2.3-beta en sus componentes semánticos.
    """
    match = SEMVER_PATTERN.match(tag_name)
    if not match:
        return {
            "is_semver": 0,
            "major": None, "minor": None, "patch": None, "prerelease": None
        }

    parts = match.groupdict()
    return {
        "is_semver": 1,
        "major": int(parts["major"]),
        "minor": int(parts["minor"]),
        "patch": int(parts["patch"]),
        "prerelease": parts["prerelease"]
    }

def create_event(
    builder: OCELBuilder,
    event_type: str,
    ts: str,
    attributes: Dict[str, Any],
    relationships: List[Tuple[str, str]] = None
) -> None:

    evt = Event(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        time=ts,
        attributes=attributes or {}
    )

    for rel in (relationships or []):
        if not rel or len(rel) != 2:
            continue
        obj_id, qualifier = rel
        if obj_id:
            evt.add_rel(obj_id, qualifier)

    builder.insert_event(evt)