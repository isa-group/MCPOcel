from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nodes
from github2ocel.extractor.graphql.queries import RELEASES_QUERY
from shared.logger import get_logger

logger = get_logger(__name__)


def fetch_releases(
    client: GitHubClient,
    page_size: int = 100,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield release nodes filtered to the configured time window.

    RELEASES_QUERY orders by CREATED_AT ASC (oldest first):
      - since: skip nodes older than the window (continue — in-window nodes come later)
      - until: early-exit once createdAt > until — all subsequent nodes are newer
    """
    logger.info("--- [Fetcher] Releases ---")

    since_iso, until_iso = client.time_window_iso

    count = 0
    for node in paginate_nodes(
        client=client,
        query=RELEASES_QUERY,
        node_type="releases",
        variables={"pageSize": page_size},
    ):
        created_at = node.get("createdAt", "")

        # Skip releases before the window (ASC order: older ones come first)
        if since_iso and created_at < since_iso:
            continue

        # Early-exit: once past until, all subsequent nodes are also past it
        if created_at > until_iso:
            logger.debug(f"[fetch_releases] Early-exit at createdAt={created_at[:10]}")
            break

        node["__type"] = "Release"
        yield node
        count += 1

    logger.info(f"--- [Fetcher] Releases done — {count} ---")