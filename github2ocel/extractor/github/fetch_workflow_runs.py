from typing import Generator, Dict, Any

from github2ocel.client.github_client import GitHubClient
from shared.logger import  get_logger

logger = get_logger(__name__)

def fetch_workflow_runs(
    client: GitHubClient,
    deep_fetch_jobs: bool = True
) -> Generator[Dict[str, Any], None, None]:
    """
    Fetches Workflow Runs and optionally performs a Deep Fetch for their jobs.
    """

    since_iso, until_iso = client.time_window_iso
    per_page = client.rest_per_page

    logger.info("--- Fetching Workflow Runs ---")

    url = f"/repos/{client.owner}/{client.repo}/actions/runs"

    params = {
        "per_page": per_page,
        "page": 1}

    if since_iso:
        # Actions format YYYY-MM-DD
        start_date = since_iso.split('T')[0]
        end_date = until_iso.split('T')[0]

        date_query = f"{start_date}..{end_date}"
        params["created"] = date_query
        logger.info(f"Applying date filter: created={date_query}")

    count_runs = 0
    count_jobs = 0
    deep_fetch_jobs: bool = True

    while True:
        try:
            response = client.rest_get(url, params=params)
            data = response.json()

            runs = data.get("workflow_runs", [])
            if not runs:
                break

            for run in runs:
                run_id = run.get("id")

                run["extracted_jobs"] = []

                if deep_fetch_jobs and run_id:
                    try:
                        jobs_url = f"/repos/{client.owner}/{client.repo}/actions/runs/{run_id}/jobs"

                        # 1 API call for Run
                        jobs_resp = client.rest_get(jobs_url, params={"per_page": 100}) # max allowed: GitHub API
                        jobs_data = jobs_resp.json()

                        extracted = jobs_data.get("jobs", [])
                        run["extracted_jobs"] = extracted

                        count_jobs += len(extracted)

                    except Exception as e:
                        logger.warning(f"Failed to fetch jobs for run {run_id}: {e}")
                        run["extracted_jobs"] = []

                run["__type"] = "WorkflowRun"
                yield run
                count_runs += 1

            if len(runs) < per_page:
                break

            params["page"] += 1

            if count_runs % 50 == 0:
                logger.info(f"Processed {count_runs} runs and {count_jobs} jobs...")

        except Exception as e:
            logger.error(f"Error fetching runs page {params['page']}: {e}")
            break

    logger.info(f"Workflow Runs extraction completed. Runs: {count_runs}, Jobs: {count_jobs}")

