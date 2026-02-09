from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from shared.logger import  get_logger

logger = get_logger(__name__)

def fetch_deployments(
    client: GitHubClient,
) -> Generator[Dict[str, Any], None, None]:
    
    per_page = client.rest_per_page


    logger.info("---Fetching deployments and statuses ---")
    endpoint_list = f"/repos/{client.owner}/{client.repo}/deployments"
    params = {
        "per_page": per_page
    }
    # Automatic pagination of the main list
    deployments_pages = client.rest_paginated(
        endpoint=endpoint_list,
        params=params,
        per_page=per_page
    )
    count = 0

    for page_deployments in deployments_pages:
        for deployment in page_deployments:

            dep_id = deployment.get("id")
            try:
                endpoint_statuses = f"{endpoint_list}/{dep_id}/statuses"

                statuses_resp = client.rest_get(endpoint_statuses)
                deployment["statuses"] = statuses_resp.json()

            except Exception as e:
                logger.warning(f"Could not fetch statuses for deployment {dep_id}: {e}")
                deployment["statuses"] = []

            deployment["__type"] = "Deployment"
            yield deployment
            count += 1

    logger.info(f"Deployments extraction completed. Total: {count}")