from dataclasses import dataclass
from typing import Optional

from shared.config.env import Env

@dataclass(frozen=True)
class APIConfig:
    """GitHub API configuration"""

    graphql_url: str
    rest_url: str
    timeout: int

    max_retries: int
    retry_backoff_min: float
    retry_backoff_max: float
    max_pages: Optional[int]
    rest_per_page: int
    graphql_per_page: int  # GraphQL (Issues, PRs)
    since_days: Optional[int]
    until_days: int
    max_commits_for_files: int  # 0 = unlimited


    @classmethod
    def from_env(cls) -> "APIConfig":

        raw_per_page = Env.optional_int("GITHUB_PER_PAGE", default=30)
        # GitHub API does not accept more than 100 items per page
        safe_per_page = min(raw_per_page, 100)

        # GraphQL Max 50 recommended to avoid timeouts
        raw_gql_page = Env.optional_int("GITHUB_GRAPHQL_PER_PAGE", default=50)
        safe_gql_page = min(raw_gql_page, 100)

        return cls(
            graphql_url=Env.str(
                "GITHUB_GRAPHQL_URL",
                default="https://api.github.com/graphql",
            ),
            rest_url=Env.str(
                "GITHUB_API_URL",
                default="https://api.github.com",
            ),
            timeout=Env.int("API_TIMEOUT", default=30),
            max_retries=Env.int("MAX_RETRIES", default=3),
            retry_backoff_min=Env.float("RETRY_BACKOFF_MIN", default=4.0),
            retry_backoff_max=Env.float("RETRY_BACKOFF_MAX", default=30.0),
            max_pages=Env.optional_int("GITHUB_MAX_PAGES"),
            rest_per_page=safe_per_page,
            graphql_per_page=safe_gql_page,
            since_days=Env.optional_int("EXTRACT_SINCE_DAYS"),
            until_days=Env.int("EXTRACT_UNTIL_DAYS", default=0),  # today
            max_commits_for_files=Env.int("MAX_COMMITS_FOR_FILES", default=0),  # 0 = unlimited
        )