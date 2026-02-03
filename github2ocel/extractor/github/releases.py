import logging

from typing import List, Dict, Any, Optional

from github2ocel.config.settings import APIConfig
from github2ocel.extractor.rest import rest_get

logger = logging.getLogger(__name__)

def fetch_releases(
    owner: str,
    repo: str,
    token: str,
    api_config: APIConfig,
    pages: Optional[int] = None,
    per_page: int = 30
) -> List[Dict[str, Any]]:
    logger.info("Fetching releases...")
    endpoint = f"/repos/{owner}/{repo}/releases"
    all_releases = []
    current_page = 1
    target_pages = pages if pages is not None else api_config.max_pages

    while True:
        if target_pages and current_page > target_pages: break
        response = rest_get(endpoint, token, api_config,
                             params={"per_page": per_page, "page": current_page})
        releases = response.json()
        if not releases: break
        all_releases.extend(releases)
        current_page += 1

    return all_releases
