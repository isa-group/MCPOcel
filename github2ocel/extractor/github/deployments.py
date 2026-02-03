import logging

from typing import List, Dict, Any, Optional

from github2ocel.config.settings import APIConfig
from github2ocel.extractor.rest import rest_get

logger = logging.getLogger(__name__)

def fetch_deployments(
    owner: str,
    repo: str,
    token: str,
    api_config: APIConfig,
    pages: Optional[int] = None,
    per_page: int = 30
) -> List[Dict[str, Any]]:
    logger.info("Fetching deployments and statuses...")
    endpoint = f"/repos/{owner}/{repo}/deployments"
    all_deployments = []
    current_page = 1
    target_pages = pages if pages is not None else api_config.max_pages

    while True:
        if target_pages and current_page > target_pages: break
        response = rest_get(endpoint, token, api_config,
                             params={"per_page": per_page, "page": current_page})
        deployments = response.json()
        if not deployments: break

        for dep in deployments:
            # Sub-resource fetch: statuses
            status_url = f"/repos/{owner}/{repo}/deployments/{dep['id']}/statuses"
            try:
                st_resp = rest_get(status_url, token, api_config)
                dep["statuses"] = st_resp.json()
            except Exception:
                dep["statuses"] = []
            all_deployments.append(dep)

        current_page += 1
    return all_deployments
