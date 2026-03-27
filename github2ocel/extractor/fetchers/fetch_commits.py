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
    Yield commits from the default branch within the configured time window.

    Filtering:
      - since: applied server-side via history(since: $since) — GitTimestamp filter
      - until: applied client-side — history() has no until param, so commits
               newer than until_iso are skipped. history returns newest-first,
               so once committedDate < since_iso we can break early.

    Args:
        page_size:  commits per page (50 recommended)
        since:      override for the since timestamp (defaults to ctx.time_window_iso)
    """
    logger.info("--- [Fetcher] Commits ---")

    since_iso, until_iso = client.time_window_iso
    effective_since = since or since_iso

    variables = {
        "pageSize": page_size,
        "cursor":   None,
        "since":    effective_since,
    }

    count = 0
    skipped_future = 0

    for node in paginate_commit_history(
        client=client,
        query=COMMITS_QUERY,
        variables=variables,
    ):
        committed_date = node.get("committedDate", "")

        # Post-filter: skip commits newer than until_iso
        # (history() has no server-side until param)
        if until_iso and committed_date > until_iso:
            skipped_future += 1
            continue

        node["__type"] = "Commit"
        yield node
        count += 1

    if skipped_future:
        logger.debug(f"[fetch_commits] {skipped_future} commits skipped (committedDate > until)")
    logger.info(f"--- [Fetcher] Commits done — {count} ---")