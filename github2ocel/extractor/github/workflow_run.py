from typing import Generator, Dict, Any

from github2ocel.client.github_client import GitHubClient
from shared.logger import  get_logger

logger = get_logger(__name__)

def fetch_workflow_runs(
    client: GitHubClient,
) -> Generator[Dict[str, Any], None, None]:

    since_iso, until_iso = client.time_window_iso
    per_page = client.rest_per_page

    logger.info("--- Fetching Workflow Runs ---")

    url = f"/repos/{client.owner}/{client.repo}/actions/runs"

    params = {"per_page": per_page, "page": 1}

    if since_iso:
        # Actions format YYYY-MM-DD
        start_date = since_iso.split('T')[0]
        end_date = until_iso.split('T')[0]

        date_query = f"{start_date}..{end_date}"
        params["created"] = date_query
        logger.info(f"Applying date filter: created={date_query}")

    count = 0

    while True:
        try:
            response = client.rest_get(url, params=params)
            data = response.json()

            runs = data.get("workflow_runs", [])
            if not runs:
                break

            for run in runs:
                run["__type"] = "WorkflowRun"
                yield run
                count += 1


            if len(runs) < per_page:
                break

            params["page"] += 1

            if count % 100 == 0:
                logger.info(f"Fetched {count} runs...")

        except Exception as e:
            logger.error(f"Error fetching runs page {params['page']}: {e}")
            break

    logger.info(f"Workflow Runs extraction completed. Total: {count}")

