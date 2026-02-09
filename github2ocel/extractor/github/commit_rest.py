from typing import Generator, Dict, Any, Optional

from github2ocel.client.github_client import GitHubClient
from shared.logger import  get_logger

logger = get_logger(__name__)


def fetch_commits_rest(
    client: GitHubClient,
    max_detailed_total: Optional[int] = None,
) -> Generator[Dict[str, Any], None, None]:
    """
    Fetches commits using the robust GitHubClient.
    WARNING: Fetching details for every commit is expensive (1 API call per commit).
    """
    since_iso, until_iso = client.time_window_iso

    logger.info("--- Fetching commits with details via REST API ---")
    if since_iso:
        logger.info(f"Time Window: {since_iso} -> {until_iso}")
    else:
        logger.info(f"Time Window: BEGINNING OF TIME -> {until_iso}")

    per_page = client.rest_per_page

    params = {
        "until": until_iso,
        "per_page": per_page
    }
    if since_iso:
        params["since"] = since_iso

    endpoint_list = f"/repos/{client.owner}/{client.repo}/commits"
    commits_pages = client.rest_paginated(
        endpoint=endpoint_list,
        params=params,
        per_page=per_page
    )
    detailed_fetched = 0

    for commits in commits_pages:
        # Process each commit on the current page
        for summary in commits:
            if max_detailed_total and detailed_fetched >= max_detailed_total:
                logger.info(f"Reached max_detailed_total limit ({max_detailed_total})")
                return

            sha = summary.get("sha")
            try:
                endpoint_detail = f"{endpoint_list}/{sha}"
                # Reuse client -> Rate Limit
                response = client.rest_get(endpoint_detail)
                commit_detailed = response.json()

                # Label mappers
                commit_detailed["__type"] = "Commit"
                yield commit_detailed
                detailed_fetched += 1
            except Exception as e:
                # If an individual commit fails and move on to the next one.
                logger.error(f"Failed to fetch details for commit {sha}: {e}")
                continue

        logger.info(f"Commits processed so far: {detailed_fetched}")

    logger.info(f"Commits extraction completed. Total: {detailed_fetched}")