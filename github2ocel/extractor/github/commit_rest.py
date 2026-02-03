import logging

from typing import List, Dict, Any, Optional

from github2ocel.config.settings import APIConfig
from github2ocel.extractor.rest import rest_get

logger = logging.getLogger(__name__)

def fetch_commits_rest(
    owner: str,
    repo: str,
    token: str,
    api_config: APIConfig,
    pages: Optional[int] = None,
    per_page: int = 30,
    max_detailed_total: Optional[int] = None,
    since: Optional[str] = None
) -> List[Dict[str, Any]]:

    logger.info("Fetching commits with details via REST API...")

    endpoint_list = f"/repos/{owner}/{repo}/commits"
    all_commits = []
    detailed_fetched = 0
    target_pages = pages if pages is not None else api_config.max_pages

    list_params = {"per_page": per_page}
    if since: list_params["since"] = since

    current_page = 1
    while True:
        if (target_pages and current_page > target_pages) or \
           (max_detailed_total and detailed_fetched >= max_detailed_total):
            break

        list_params["page"] = current_page
        response = rest_get(endpoint_list, token, api_config, params=list_params)
        commits_summary = response.json()

        if not commits_summary: break

        for summary in commits_summary:
            if max_detailed_total and detailed_fetched >= max_detailed_total: break

            sha = summary["sha"]
            endpoint_detail = f"/repos/{owner}/{repo}/commits/{sha}"

            try:
                # Every single commit detail call is now protected by the Limiter
                detail_resp = rest_get(endpoint_detail, token, api_config)
                all_commits.append(detail_resp.json())
                detailed_fetched += 1
            except Exception as e:
                logger.warning(f"Skipping commit {sha} due to error: {e}")
                continue

        current_page += 1
        logger.info(f"Detailed commits: {detailed_fetched} (Last page: {current_page-1})")

    return all_commits


