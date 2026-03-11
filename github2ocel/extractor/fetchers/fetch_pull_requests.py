from typing import Generator, Dict, Any, Optional
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nodes
from github2ocel.extractor.graphql.queries import PULL_REQUESTS_QUERY

from shared.logger import get_logger

logger = get_logger(__name__)

def fetch_pull_requests(
    client: GitHubClient,
    page_size: int = 50,
    total: int = 0,
    since: Optional[str] = None,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield PR nodes ordered by updatedAt ASC.

    With since: include PRs created OR updated within the window.
      - createdAt >= since  → new PR in window
      - updatedAt >= since  → existing PR with activity in window
    Without since: yield all PRs.

    Note: GitHub GraphQL has no native since filter for PRs,
    so filtering is post-pagination on both createdAt and updatedAt.
    """
    logger.info(f"--- [Fetcher] Pull Requests (pageSize={page_size}) ---")

    count = 0
    skipped = 0

    for node in paginate_nodes(
        client=client,
        query=PULL_REQUESTS_QUERY,
        node_type="pullRequests",
        variables={"pageSize": page_size},
        total=total,
        label="prs",
    ):
        if since:
            created_at = node.get("createdAt", "")
            updated_at = node.get("updatedAt", "")
            if created_at < since and updated_at < since:
                skipped += 1
                continue

        node["__type"] = "PullRequest"
        yield node
        count += 1

    if since and skipped:
        logger.info(f"  [fetch_pull_requests] {skipped} PRs skipped (createdAt and updatedAt < {since[:10]})")