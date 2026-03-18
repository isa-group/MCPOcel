from typing import Generator, Dict, Any, Optional
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nodes
from github2ocel.extractor.graphql.queries import ISSUES_QUERY
from shared.logger import get_logger

logger = get_logger(__name__)


def fetch_issues(
    client: GitHubClient,
    page_size: int = 50,
    total: int = 0,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield issue nodes with activity in the time window.

    Filtering strategy:
      - API-level: filterBy: { since } → updatedAt >= since  (server-side, efficient)
      - Post-filter: updatedAt <= until  (client-side, GitHub has no native until for issues)

    orderBy UPDATED_AT ASC is coherent with the since filter: both operate on updatedAt,
    so paginación cursor advances correctly through the filtered set.
    """
    logger.info(f"--- [Fetcher] Issues (pageSize={page_size}) ---")

    since, until_iso = client.ctx.time_window_iso

    variables = {"pageSize": page_size}
    if since:
        variables["since"] = since

    skipped = 0
    for node in paginate_nodes(
        client=client,
        query=ISSUES_QUERY,
        node_type="issues",
        variables=variables,
        total=total,
        label="issues",
    ):
        # Post-filter: drop issues whose updatedAt is beyond the until boundary
        updated_at = node.get("updatedAt", "")
        if updated_at > until_iso:
            skipped += 1
            break

        node["__type"] = "Issue"
        yield node

    if skipped:
        logger.info(f"  [fetch_issues] {skipped} issues skipped (updatedAt > {until_iso[:10]})")