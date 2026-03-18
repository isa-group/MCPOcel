from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from shared.logger import get_logger

logger = get_logger(__name__)


def fetch_workflow_runs(
    client: GitHubClient,
    page_size: int = 100,
    fetch_jobs: bool = True,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield WorkflowRun dicts, each enriched with an "extracted_jobs" list.
    Job steps are included inside each job for WorkflowStep objects.

    Args:
        page_size:  runs per REST page (from compute_page_sizes)
        fetch_jobs: if True, makes a secondary REST call per run to get jobs
    """
    logger.info("--- [Fetcher] Workflow Runs + Jobs ---")

    since_iso, until_iso = client.ctx.time_window_iso

    params: Dict[str, Any] = {"per_page": page_size, "page": 1}

    if since_iso:
        start_date = since_iso.split("T")[0]
        end_date   = until_iso.split("T")[0]
        params["created"] = f"{start_date}..{end_date}"
        logger.info(f"[fetch_workflow_runs] Date filter: {params['created']}")

    url = f"/repos/{client.owner}/{client.repo}/actions/runs"
    count_runs = 0
    count_jobs = 0

    while True:
        try:
            data = client.rest(url, params=params)
            runs = data.get("workflow_runs", [])

            if not runs:
                break

            for run in runs:
                run_id = run.get("id")
                run["extracted_jobs"] = []

                if fetch_jobs and run_id:
                    try:
                        jobs_url = f"/repos/{client.owner}/{client.repo}/actions/runs/{run_id}/jobs"
                        jobs_data = client.rest(jobs_url, params={"per_page": 100})
                        run["extracted_jobs"] = jobs_data.get("jobs", [])
                        count_jobs += len(run["extracted_jobs"])
                    except Exception as e:
                        logger.warning(f"[fetch_workflow_runs] Jobs failed for run {run_id}: {e}")

                run["__type"] = "WorkflowRun"
                yield run
                count_runs += 1

            if len(runs) < page_size:
                break

            params["page"] += 1

            if count_runs % 50 == 0:
                logger.info(f"[fetch_workflow_runs] {count_runs} runs, {count_jobs} jobs…")

        except Exception as e:
            logger.error(f"[fetch_workflow_runs] Failed on page {params['page']}: {e}")
            break

    logger.info(f"--- [Fetcher] Workflow Runs done — {count_runs} runs, {count_jobs} jobs ---")
