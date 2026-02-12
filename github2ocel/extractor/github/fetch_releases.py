from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from shared.logger import  get_logger

logger = get_logger(__name__)

def fetch_releases(
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
