from typing import List, Dict, Any
from github2ocel.client.github_client import GitHubClient
from shared.logger import get_logger

logger = get_logger(__name__)


from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from shared.logger import get_logger

logger = get_logger(__name__)


def fetch_branches(
    client: GitHubClient,
) -> Generator[Dict[str, Any], None, None]:
    logger.info("--- [Fetcher] Branches ---")

    endpoint = f"/repos/{client.owner}/{client.repo}/branches"
    count = 0

    for page in client.rest_paginated(endpoint=endpoint):
        for branch in page:
            branch["__type"] = "Branch"
            yield branch
            count += 1

    logger.info(f"--- [Fetcher] Branches done — {count} ---")
