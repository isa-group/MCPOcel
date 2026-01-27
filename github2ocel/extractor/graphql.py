import logging
import time
import requests
from typing import List, Dict, Any, Optional

from github2ocel.config.settings import APIConfig

logger = logging.getLogger(__name__)

ISSUES_QUERY = """
query($owner: String!, $repo: String!, $cursor: String, $pageSize: Int!) {
  repository(owner: $owner, name: $repo) {
    issues(
      first: $pageSize,
      after: $cursor,
      orderBy: {field: CREATED_AT, direction: ASC}
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        title
        state
        createdAt
        closedAt
        author { login }
        labels(first: 20) {
          nodes { name color }
        }
        comments(first: 20) {
          nodes {
            createdAt
            author { login }
          }
        }
      }
    }
  }
}
"""

PRS_QUERY = """
query($owner: String!, $repo: String!, $cursor: String, $pageSize: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequests(
      first: $pageSize,
      after: $cursor,
      orderBy: {field: CREATED_AT, direction: ASC}
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        title
        state
        createdAt
        closedAt
        merged
        mergedAt
        author { login }
        labels(first: 20) {
          nodes { name color }
        }
        reviews(first: 20) {
          nodes {
            state
            submittedAt
            author { login }
          }
        }
        comments(first: 20) {
          nodes {
            createdAt
            author { login }
          }
        }
      }
    }
  }
}
"""

class RateLimitExceeded(RuntimeError):
    pass

def _run_graphql_query(
        query: str,
        variables: Dict[str, Any],
        token: str,
        api_config: APIConfig,
) -> Dict[str, Any]:

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    attempt = 0
    while attempt < api_config.max_retries:
        try:
            response = requests.post(
                api_config.graphql_url,
                json={"query": query, "variables": variables},
                headers=headers,
                timeout=api_config.timeout,
            )

            if response.status_code == 403: # Explicit Handling of HTTP 403 (REST API Rate Limit/General)
                remaining = response.headers.get("x-ratelimit-remaining") # GitHub standard header
                if remaining == "0":
                    reset_time = response.headers.get("x-ratelimit-reset", "Unknown")
                    logger.error(f"GitHub API Rate Limit Hit! Reset at epoch: {reset_time}")
                    raise RateLimitExceeded("HTTP 403: Rate Limit Exceeded")

            response.raise_for_status()

            # Error Handling within the GraphQL Body
            payload = response.json()
            if "errors" in payload:
                error_msg = payload["errors"][0].get("message", "Unknown GraphQL error")

                # Detect Secondary Rate Limits (common in complex GraphQL)
                if "rate limit" in error_msg.lower():
                    logger.error("GraphQL Secondary Rate Limit Hit")
                    raise RateLimitExceeded(f"GraphQL Error: {error_msg}")
                raise RuntimeError(f"GraphQL API Error: {error_msg}")

            return payload.get("data", {})

        except (requests.RequestException, RuntimeError, RateLimitExceeded) as e:
            # Help with secondary limits.
            attempt += 1
            if attempt >= api_config.max_retries:
                logger.error(f"Failed after {attempt} attempts. Last error: {e}")
                raise e

            sleep_time = min(
                api_config.retry_backoff_max,
                api_config.retry_backoff_min * (2 ** (attempt - 1))
            )
            logger.warning(f"Attempt {attempt} failed ({e}). Retrying in {sleep_time}s...")
            time.sleep(sleep_time)

    return {}


def _paginate_graphql(
        query: str,
        node_type: str,
        owner: str,
        repo: str,
        token: str,
        pages: Optional[int],
        page_size: int,
        api_config: APIConfig,
) -> List[Dict[str, Any]]:

    all_nodes: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    current_page = 1

    logger.info(f"Fetching {node_type} (Max pages: {pages})...")

    while True:
        if pages is not None and current_page > pages:
            break

        variables = {
            "owner": owner,
            "repo": repo,
            "cursor": cursor,
            "pageSize": page_size
        }

        # Catch exceptions here
        data = _run_graphql_query(query, variables, token, api_config)

        repo_data = data.get("repository", {})
        if not repo_data:
            logger.warning(f"Repository data not found/accessible for {owner}/{repo}")
            break

        container = repo_data.get(node_type, {})
        nodes = container.get("nodes", [])

        # Filter null values
        valid_nodes = [n for n in nodes if n is not None]
        all_nodes.extend(valid_nodes)

        page_info = container.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            logger.info(f"Reached last page of {node_type}.")
            break

        cursor = page_info.get("endCursor")
        current_page += 1
        logger.info(f"Fetched page {current_page} of {node_type}...")
    logger.info(f"Fetched {len(all_nodes)} {node_type}.")
    return all_nodes

# PUBLIC API
def fetch_github_data(
        owner: str,
        repo: str,
        token: str,
        api_config: APIConfig,
        pages: int = 3,
        per_page: int = 50,
) -> List[Dict[str, Any]]:
    """
    Fetch Issues and Pull Requests via GitHub GraphQL API.
    Returns a unified list of raw nodes.
    """
    if pages is not None and pages < 1:
        logger.warning("Configuration requested 0 pages via GraphQL. Skipping.")
        return []

    issues = _paginate_graphql(
        query=ISSUES_QUERY,
        node_type="issues",
        owner=owner,
        repo=repo,
        token=token,
        pages=pages,
        page_size=per_page,
        api_config=api_config
    )

    prs = _paginate_graphql(
        query=PRS_QUERY,
        node_type="pullRequests",
        owner=owner,
        repo=repo,
        token=token,
        pages=pages,
        page_size=per_page,
        api_config=api_config
    )

    # Prevents subtle bugs from shared references
    tagged_issues = [{"__type": "Issue", **i} for i in issues]
    tagged_prs = [{"__type": "PullRequest", **p} for p in prs]

    total_nodes = tagged_issues + tagged_prs
    logger.info(f"Total GraphQL nodes extracted: {len(total_nodes)}")

    return total_nodes
