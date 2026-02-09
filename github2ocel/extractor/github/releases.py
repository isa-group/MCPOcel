from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from shared.logger import  get_logger

logger = get_logger(__name__)

def fetch_releases(
    client: GitHubClient,
) -> Generator[Dict[str, Any], None, None]:
    
    per_page = client.rest_per_page

    logger.info("--- Fetching Releases ---")
    params = {"per_page": per_page}

    releases_pages = client.rest_paginated(
        endpoint=f"/repos/{client.owner}/{client.repo}/releases",
        params=params
    )

    count = 0
    for page_releases in releases_pages:
        for release in page_releases:
            release["__type"] = "Release"
            yield release
            count += 1

    logger.info(f"Releases extraction completed. Total: {count}")
