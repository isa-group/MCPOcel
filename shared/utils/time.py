"""Time utilities for OCEL processing.

Provides functions for parsing and formatting ISO 8601 timestamps.
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def parse_time(iso_str: Optional[str]) -> Optional[datetime]:
    """
    Parses ISO 8601 timestamp string to datetime object.
    
    Args:
        iso_str: ISO 8601 formatted timestamp string.
        
    Returns:
        datetime object if parsing succeeds, None otherwise.
    """
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError:
        logger.warning(f"Failed to parse timestamp: {iso_str}")
        return None


def format_timestamp(dt: Optional[datetime]) -> Optional[str]:
    """
    Formats datetime object to ISO 8601 string.
    
    Args:
        dt: datetime object to format.
        
    Returns:
        ISO 8601 formatted string with 'Z' suffix, or None if input is None.
    """
    if not dt:
        return None
    return dt.isoformat() + "Z"


def make_id(*parts) -> str:
    """
    Creates a consistent ID from multiple parts.
    
    Cleans each part by removing spaces, slashes, and colons,
    then joins them with underscores.
    
    Args:
        *parts: Variable number of parts to combine into an ID.
        
    Returns:
        Cleaned and concatenated ID string.
        
    Example:
        >>> make_id("user", "john doe", 123)
        'user_john_doe_123'
    """
    cleaned = []
    for p in parts:
        if p is None:
            continue
        s = str(p).replace(" ", "_").replace("/", "_").replace(":", "")
        cleaned.append(s)
    return "_".join(cleaned)
