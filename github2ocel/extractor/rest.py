import logging
import time
import requests
from typing import List, Dict, Any, Optional

from github2ocel.config.settings import APIConfig

logger = logging.getLogger(__name__)

def _calculate_sleep_time(response: requests.Response) -> float:
    """
    Calculate how long to sleep based on standard headers.
    Prioridad: Retry-After > X-RateLimit-Reset
    """
    # 1. Retry-After (Standard HTTP / GitHub Secondary Limits)
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            return 0.0

    # 2. X-RateLimit-Reset (GitHub Primary Limits)
    remaining = response.headers.get("X-RateLimit-Remaining")
    if remaining == "0":
        reset_timestamp = int(response.headers.get("X-RateLimit-Reset", 0))
        now = int(time.time())
        # We add 1s margin to ensure the limit has actually reset
        return max(0.0, float(reset_timestamp - now + 1))

    return 0.0


def _rest_get(
        endpoint: str,
        token: str,
        api_config: APIConfig,
        params: Optional[Dict[str, Any]] = None,
) -> requests.Response:

    url = f"{api_config.rest_url}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    params = params or {}

    # SAFETY: If the blockage lasts longer than 5 minutes, we abort.
    MAX_SLEEP_ALLOWED = 300.0

    # Network error handling / Timeouts / 5xx
    for attempt in range(1, api_config.max_retries + 1):
        try:
            # Rate Limit Management (403/429)
            while True:
                response = requests.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=api_config.timeout,
                )
                # Success case
                if 200 <= response.status_code < 300:
                    return response

                # Rate Limit Case (403/429)
                if response.status_code in (403, 429):
                    sleep_seconds = _calculate_sleep_time(response)
                    if sleep_seconds > 0:
                        if sleep_seconds > MAX_SLEEP_ALLOWED:
                            logger.error(f"Rate limit reset is too far ({sleep_seconds}s). Aborting.")
                            response.raise_for_status()

                        logger.warning(f"Rate limit hit. Sleeping for {sleep_seconds}s...")
                        time.sleep(sleep_seconds)
                        continue # Retry after sleeping
                    else:
                        logger.error("Rate limit hit but no reset time provided by GitHub.")
                        response.raise_for_status()

                # Other Case (401, 404, etc.))
                response.raise_for_status()

        except requests.RequestException as e:
            if attempt == api_config.max_retries:
                logger.error(f"REST Request failed permanently after {attempt} attempts: {url}")
                raise

            # Exponential Backoff
            wait = min(
                api_config.retry_backoff_max,
                api_config.retry_backoff_min * (2 ** (attempt - 1))
            )

            logger.warning(
                f"Connection error (Attempt {attempt}/{api_config.max_retries}). "
                f"Retrying in {wait}s... Error: {e}"
            )
            time.sleep(wait)

    raise RuntimeError("Unreachable REST client state")

# Extractors
def fetch_workflow_runs(
        owner: str,
        repo: str,
        token: str,
        api_config: APIConfig,
        pages: Optional[int] = None,
        per_page: int = 50,
) -> List[Dict[str, Any]]:
    """
    Fetch workflow runs from GitHub REST API.
    Returns RAW data.
    """
    logger.info("Fetching workflow runs via REST API...")

    endpoint = f"/repos/{owner}/{repo}/actions/runs"
    all_runs: List[Dict[str, Any]] = []

    target_pages = pages if pages is not None else api_config.max_pages
    page = 1

    while True:
        if target_pages is not None and page > target_pages:
            logger.info(f"Reached pagination limit of {target_pages} pages.")
            break

        response = _rest_get(
            endpoint,
            token,
            api_config,
            params={"per_page": per_page, "page": page},
        )

        data = response.json()
        runs = data.get("workflow_runs", [])

        if not runs:
            break

        all_runs.extend(runs)
        logger.info(f"Fetched {len(all_runs)} workflow runs (Page {page})...")
        page += 1
    return all_runs


def fetch_commits_rest(
        owner: str,
        repo: str,
        token: str,
        api_config: APIConfig,
        pages: Optional[int] = None,
        per_page: int = 30,
        max_detailed_total: int = 20,
) -> List[Dict[str, Any]]:
    """
    Fetch commits list and then fetch DETAILS for each commit.
    """
    logger.info("Fetching commits via REST API...")

    endpoint_list = f"/repos/{owner}/{repo}/commits"
    all_commits: List[Dict[str, Any]] = []
    detailed_fetched = 0
    target_pages = pages if pages is not None else api_config.max_pages

    current_page = 1

    while True:
        if target_pages is not None and current_page > target_pages:
            logger.info(f"Reached pagination limit of {target_pages} pages.")
            break
        if detailed_fetched >= max_detailed_total:
            break

        try:
            response = _rest_get(
                endpoint_list,
                token,
                api_config,
                params={"per_page": per_page, "page": current_page},
            )
            commits_summary = response.json()

            if not commits_summary:
                break

            # Fetch Details (N+1)
            for summary in commits_summary:
                if detailed_fetched >= max_detailed_total:
                    break

                sha = summary["sha"]
                endpoint_detail = f"/repos/{owner}/{repo}/commits/{sha}"

                try:
                    detail_resp = _rest_get(endpoint_detail, token, api_config)
                    all_commits.append(detail_resp.json())
                    detailed_fetched += 1

                    # Micro-throttle
                    time.sleep(0.1)

                except Exception as e:
                    logger.warning(f"Skipping commit {sha} due to error: {e}")
                    continue
            current_page += 1
            logger.info(f"Fetched {detailed_fetched} detailed commits so far (Page {current_page - 1})...")

        except Exception:
            logger.error(f"Failed to fetch commits list page {current_page}")
            raise

    logger.info("Fetched %d detailed commits", len(all_commits))
    return all_commits

def fetch_releases(
    owner: str,
    repo: str,
    token: str,
    api_config: APIConfig,
    pages: int = 1,
    per_page: int = 30
) -> List[Dict[str, Any]]:
    """
    Fetch published Releases (and tags).
    """
    logger.info("Fetching releases via REST API...")
    endpoint = f"/repos/{owner}/{repo}/releases"
    all_releases: List[Dict[str, Any]] = []

    for page in range(1, pages + 1):
        try:
            response = _rest_get(
                endpoint,
                token,
                api_config,
                params={"per_page": per_page, "page": page},
            )
            releases = response.json()
            if not releases:
                break
            all_releases.extend(releases)
        except Exception:
            logger.error(f"Failed to fetch releases page {page}.")
            raise

    logger.info(f"Fetched {len(all_releases)} releases.")
    return all_releases
