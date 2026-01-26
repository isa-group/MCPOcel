import requests
from config.logging_config import get_logger

logger = get_logger(__name__)

def fetch_workflow_runs(owner, repo, token, pages=3):
    logger.info("Starting REST Workflows...")
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    all_runs = []
    for page in range(1, pages + 1):
        resp = requests.get(url, headers=headers, params={"per_page": 50, "page": page})
        if resp.status_code != 200:
            logger.error(f"Error in REST Workflows: HTTP {resp.status_code}")
            break

        runs = resp.json().get("workflow_runs", [])
        if not runs:
            break

        all_runs.extend(runs)
        logger.info(f"   -> Page {page}: {len(runs)} runs fetched")

    return all_runs


def fetch_commits_rest(owner, repo, token, pages=3):

    logger.info("Starting REST Commits...")
    url = f"https://api.github.com/repos/{owner}/{repo}/commits"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    all_commits = []

    for page in range(1, pages + 1):
        try:
            resp = requests.get(url, headers=headers, params={"per_page": 30, "page": page})
            if resp.status_code != 200:
                logger.error(f"Error in REST Commits: HTTP {resp.status_code}")
                break

            commits_summary = resp.json()
            if not commits_summary: break

            logger.info(f"   -> Page {page}: Processing {len(commits_summary)} commits...")

            limit_detailed = 0
            for c in commits_summary:
                # Limit detailed fetching to avoid rate limits during testing
                if limit_detailed >= 20 and page == 1: break
                limit_detailed += 1

                sha = c["sha"]
                det_resp = requests.get(f"{url}/{sha}", headers=headers)
                if det_resp.status_code == 200:
                    all_commits.append(det_resp.json())
                else:
                    logger.warning(f"Could not fetch details for commit {sha}")
        except Exception:
            logger.exception(f"Exception during REST Commits page {page}")
            break

    return all_commits