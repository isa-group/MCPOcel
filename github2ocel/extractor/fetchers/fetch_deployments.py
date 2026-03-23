from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nodes
from github2ocel.extractor.graphql.queries import DEPLOYMENTS_QUERY
from shared.logger import get_logger

logger = get_logger(__name__)

def fetch_deployments(
    client: GitHubClient,
    page_size: int = 40,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield deployment nodes filtered to the configured time window.

    DEPLOYMENTS_QUERY orders by CREATED_AT DESC (newest first), which enables
    early-exit once we pass below since_iso — all subsequent nodes will also
    be older, so there is no need to continue paginating.
    """
    logger.info("--- [Fetcher] Deployments ---")

    since_iso, until_iso = client.ctx.time_window_iso

    count = 0
    skipped = 0
    for node in paginate_nodes(
        client=client,
        query=DEPLOYMENTS_QUERY,
        node_type="deployments",
        variables={"pageSize": page_size},
    ):
        created_at = node.get("createdAt", "")

        # Nodes arrive newest-first. Skip those after until (recent deployments
        # outside the window) and continue — there may be more in-window nodes ahead.
        if created_at > until_iso:
            skipped += 1
            continue

        # Early-exit: once we see a node older than since, all following nodes
        # will also be older (DESC order). Stop paginating immediately.
        if since_iso and created_at < since_iso:
            logger.debug(f"[fetch_deployments] Early-exit at createdAt={created_at[:10]} (before since={since_iso[:10]})")
            break

        node["__type"] = "Deployment"
        yield node
        count += 1

    if skipped:
        logger.debug(f"[fetch_deployments] {skipped} deployments skipped (createdAt > until)")

    logger.info(f"--- [Fetcher] Deployments done — {count} total, {skipped} Issues skipped ---")