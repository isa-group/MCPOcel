from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from shared.config.env import Env
from shared.utils.time import to_iso8601
from github2ocel.config.settings import APIConfig
from github2ocel.config.profiles import ExtractionProfile, get_profile_from_env, get_profile_vars
from typing import Dict


@dataclass(frozen=True)
class RepoContext:
    owner: str
    repo: str
    token: str
    api: APIConfig
    profile: ExtractionProfile

    @classmethod
    def from_env(cls) -> "RepoContext":
        return cls(
            owner=Env.str("GITHUB_OWNER"),
            repo=Env.str("GITHUB_REPO"),
            token=Env.str("GITHUB_TOKEN"),
            api=APIConfig.from_env(),
            profile=get_profile_from_env(),
        )

    @property
    def profile_vars(self) -> Dict[str, bool]:
        """Returns the boolean flags for the active profile."""
        return get_profile_vars(self.profile.value)

    @property
    def time_window_iso(self) -> Tuple[Optional[str], str]:
        """
        Retorna (since_iso, until_iso).
        Si since_iso es None, significa 'desde el principio'.
        """
        now = datetime.now(timezone.utc)
        date_until = now - timedelta(days=self.api.until_days)
        until_iso = date_until.isoformat()

        # CASE: Complete History
        if self.api.since_days is None:
            return None, until_iso

        # CASE: Defined time window
        date_since = now - timedelta(days=self.api.since_days)

        if date_since > date_until:
            raise ValueError("Configuration Error: 'since' cannot be after 'until'")

        return to_iso8601(date_since), until_iso