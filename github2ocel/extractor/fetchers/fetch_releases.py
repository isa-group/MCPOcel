from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient

from github2ocel.client.paginator import paginate_nodes
from github2ocel.extractor.graphql.queries import RELEASES_QUERY

from shared.logger import  get_logger

logger = get_logger(__name__)

def fetch_releases_rest(
    client: GitHubClient,
) -> Generator[Dict[str, Any], None, None]:
    """
    Fetches repository releases using standard pagination.
    """
    logger.info("--- Fetching Releases ---")


    releases_pages = client.rest_paginated(
        endpoint=f"/repos/{client.owner}/{client.repo}/releases"
    )

    count = 0
    for page_releases in releases_pages:
        for release in page_releases:
            release["__type"] = "Release"
            yield release
            count += 1

    logger.info(f"Releases extraction completed. Total: {count}")


def fetch_releases(
    client: GitHubClient,
    page_size: int = 100,
) -> Generator[Dict[str, Any], None, None]:
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
        if since_iso and created_at < since_iso:
            continue
        if created_at > until_iso:
            continue
        node["__type"] = "Release"
        yield node
        count += 1

    logger.info(f"--- [Fetcher] Releases done — {count} ---")