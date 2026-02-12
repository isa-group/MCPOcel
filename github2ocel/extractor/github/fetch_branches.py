import logging
from typing import List, Dict, Any
from github2ocel.client.github_client import GitHubClient

logger = logging.getLogger(__name__)

def fetch_branches(client: GitHubClient) -> List[Dict[str, Any]]:
    """
    Download ALL branches from the repository using REST pagination.
    Endpoint: GET /repos/{owner}/{repo}/branches
    """
    logger.info("--- Fetching Branches ---")
    all_branches = []
    page = 1
    per_page = client.rest_per_page

    while True:
        try:
            endpoint = f"/repos/{client.owner}/{client.repo}/branches"
            params = {"page": page, "per_page": per_page}

            response = client.rest_get(endpoint, params=params)
            batch = response.json()

            if not batch:
                break

            all_branches.extend(batch)
            logger.info(f"Branches: Fetched page {page} ({len(batch)} branches)")

            if len(batch) < per_page:
                break # Last page

            page += 1

        except Exception as e:
            logger.error(f"Failed to fetch branches on page {page}: {e}")
            break

    logger.info(f"Branches extraction completed. Total: {len(all_branches)}")
    return all_branches