
from typing import Generator, Dict, Any, Optional
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_commit_history
from github2ocel.extractor.graphql.queries import COMMITS_QUERY
from shared.logger import get_logger

logger = get_logger(__name__)


def fetch_commits(
    client: GitHubClient,
    page_size: int = 50,
    since: Optional[str] = None,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield all commits from the default branch.

    Args:
        page_size:  commits per page (50 recommended; files field is expensive)
        since:      ISO timestamp to filter commits (from time window config)
    """
    logger.info("--- [Fetcher] Commits ---")

    since_iso, until_iso = client.ctx.time_window_iso
    effective_since = since or since_iso  # allow override

    variables = {
        "pageSize": page_size,
        "cursor": None,
        "since": effective_since,
    }
    count = 0
    for node in paginate_commit_history(
        client=client,
        query=COMMITS_QUERY,
        variables=variables,
    ):
        node["__type"] = "Commit"
        yield node
        count =+ 1

    logger.info(f"--- [Fetcher] Deployments done — {count} ---")