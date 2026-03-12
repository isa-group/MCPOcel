from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from github2ocel.config.settings import APIConfig
from shared.utils.time import to_iso8601

def compute_time_window(api: APIConfig) -> Tuple[Optional[str], str]:
    """
    Computes (since_iso, until_iso) once at construction time.
    since_iso is None when extracting complete history.
    """
    now = datetime.now(timezone.utc)
    date_until = now - timedelta(days=api.until_days)
    until_iso = date_until.isoformat()

    if api.since_days is None:
        return None, until_iso

    date_since = now - timedelta(days=api.since_days)

    if date_since > date_until:
        raise ValueError("Configuration Error: 'since' cannot be after 'until'")

    return to_iso8601(date_since), until_iso