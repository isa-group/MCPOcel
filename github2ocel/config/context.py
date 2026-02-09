from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from shared.config.env import Env
from github2ocel.config.settings import APIConfig


@dataclass(frozen=True)
class RepoContext:
    owner: str
    repo: str
    token: str
    visibility: str
    api: APIConfig

    @classmethod
    def from_env(cls) -> "RepoContext":
        return cls(
            owner=Env.str("GITHUB_OWNER"),
            repo=Env.str("GITHUB_REPO"),
            token=Env.str("GITHUB_TOKEN"),
            visibility=Env.str("GITHUB_VISIBILITY", default="public"),
            api=APIConfig.from_env(),
        )

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

        return date_since.isoformat(), until_iso