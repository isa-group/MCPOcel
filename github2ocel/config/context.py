from dataclasses import dataclass, field
from typing import Tuple, Optional, Dict
from shared.config.env import Env
from github2ocel.config.settings import APIConfig
from github2ocel.config.profiles import ExtractionProfile, get_profile_from_env, get_profile_vars
from datetime import datetime, timedelta, timezone
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

@dataclass(frozen=True)
class RepoContext:
    owner: str
    repo: str
    token: str
    api: APIConfig
    profile: ExtractionProfile
    # Computed once at construction — avoids drift across a long extraction
    time_window_iso: Tuple[Optional[str], str] = field(compare=False)

    @classmethod
    def from_env(cls) -> "RepoContext":
        api = APIConfig.from_env()
        return cls(
            owner=Env.str("GITHUB_OWNER"),
            repo=Env.str("GITHUB_REPO"),
            token=Env.str("GITHUB_TOKEN"),
            api=api,
            profile=get_profile_from_env(),
            time_window_iso=compute_time_window(api),
        )

    @property
    def profile_vars(self) -> Dict[str, bool]:
        """Returns the boolean flags for the active profile."""
        return get_profile_vars(self.profile.value)