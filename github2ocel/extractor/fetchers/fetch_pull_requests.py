from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nodes
from github2ocel.extractor.graphql.queries import PULL_REQUESTS_QUERY

from shared.logger import get_logger

logger = get_logger(__name__)

def fetch_pull_requests(
    client: GitHubClient,
    page_size: int = 50,
    total: int = 0,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield PR nodes with activity in the time window, ordered by updatedAt ASC.

    Filtering strategy (GitHub GraphQL has no native since/until for PRs):
      - since: post-filter — include if createdAt >= since OR updatedAt >= since
                             (new PR in window, OR existing PR with activity in window)
      - until: post-filter — exclude if createdAt > until AND updatedAt > until
    Without since/until: yield all PRs.
    """
    logger.info(f"--- [Fetcher] Pull Requests (pageSize={page_size}) ---")

    since, until_iso = client.ctx.time_window_iso

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
        created_at = node.get("createdAt", "")
        updated_at = node.get("updatedAt", "")

        # since: drop PRs with no activity in the window
        if since and created_at < since and updated_at < since:
            skipped += 1
            continue

        # until: drop PRs that only exist after the window
        if created_at > until_iso and updated_at > until_iso:
            skipped += 1
            break

        node["__type"] = "PullRequest"
        yield node
        count += 1

    if skipped:
        logger.info(f"  [fetch_pull_requests] {skipped} PRs skipped (outside time window)")