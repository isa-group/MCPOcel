import logging

from typing import List, Dict, Any, Optional

from github2ocel.config.settings import APIConfig
from github2ocel.extractor.rest import rest_get

logger = logging.getLogger(__name__)

def fetch_workflow_runs(
    owner: str,
    repo: str,
    token: str,
    api_config: APIConfig,
    pages: Optional[int] = None,
    per_page: int = 50,
) -> List[Dict[str, Any]]:
    logger.info("Fetching workflow runs via REST API...")
    endpoint = f"/repos/{owner}/{repo}/actions/runs"
    all_runs = []

    target_pages = pages if pages is not None else api_config.max_pages
    current_page = 1

    while True:
        if target_pages and current_page > target_pages: break

        response = rest_get(endpoint, token, api_config,
                             params={"per_page": per_page, "page": current_page})
        data = response.json()
        runs = data.get("workflow_runs", [])

        if not runs: break

        all_runs.extend(runs)
        logger.info(f"Fetched {len(all_runs)} workflow runs (Page {current_page})...")
        current_page += 1

    return all_runs

