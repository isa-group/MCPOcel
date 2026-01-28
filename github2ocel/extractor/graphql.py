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

            # Handling Rate Limits at the HTTP (403/429)
            if response.status_code in (403, 429):
                remaining = response.headers.get("x-ratelimit-remaining")
                if remaining == "0":
                    reset_time = response.headers.get("x-ratelimit-reset", "Unknown")
                    logger.error(f"GitHub API Rate Limit Hit! Reset at: {reset_time}")
                    raise RateLimitExceeded(f"HTTP {response.status_code}: Rate Limit Exceeded")

            response.raise_for_status()

            # Error handling within the GraphQL body
            payload = response.json()
            if "errors" in payload:
                error_msg = payload["errors"][0].get("message", "Unknown GraphQL error")

                # Detect secondary limits (common in heavy queries)
                if "rate limit" in error_msg.lower():
                    logger.error("GraphQL Secondary Rate Limit Hit")
                    raise RateLimitExceeded(f"GraphQL Error: {error_msg}")
                raise RuntimeError(f"GraphQL API Error: {error_msg}")

            return payload.get("data", {})

        except (requests.RequestException, RuntimeError, RateLimitExceeded):
            attempt += 1
            if attempt >= api_config.max_retries:
                logger.error(f"GraphQL failed after {attempt} attempts.")
                raise # original traceback

            sleep_time = min(
                api_config.retry_backoff_max,
                api_config.retry_backoff_min * (2 ** (attempt - 1))
            )
            logger.warning(f"GraphQL Attempt {attempt} failed. Retrying in {sleep_time}s...")
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
    all_nodes = []
    cursor = None
    current_page = 1

    target_pages = pages if pages is not None else api_config.max_pages

    logger.info(f"Fetching {node_type} (Max pages: {target_pages or 'Inf'})...")

    while True:
        if target_pages and current_page > target_pages:
            break

        variables = {
            "owner": owner,
            "repo": repo,
            "cursor": cursor,
            "pageSize": page_size
        }

        data = _run_graphql_query(query, variables, token, api_config)
        repo_data = data.get("repository", {})
        if not repo_data:
            logger.warning(f"Repository data not accessible for {owner}/{repo}")
            break

        container = repo_data.get(node_type, {})
        nodes = container.get("nodes", [])

        # Security filter for null nodes
        valid_nodes = [n for n in nodes if n is not None]
        all_nodes.extend(valid_nodes)

        page_info = container.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break

        cursor = page_info.get("endCursor")
        logger.debug(f"{node_type} cursor: {cursor}") # For tracing pagination
        current_page += 1
        logger.info(f"Fetched page {current_page} of {node_type}...")

    logger.info(f"Fetched total {len(all_nodes)} {node_type}.")
    return all_nodes

def fetch_github_data(
    owner: str,
    repo: str,
    token: str,
    api_config: APIConfig,
    pages: Optional[int] = None,
    per_page: int = 50,
) -> List[Dict[str, Any]]:

    issues = _paginate_graphql(ISSUES_QUERY, "issues", owner, repo, token, pages, per_page, api_config)
    prs = _paginate_graphql(PRS_QUERY, "pullRequests", owner, repo, token, pages, per_page, api_config)

    # Labelling for the Mapper
    tagged_issues = [{"__type": "Issue", **i} for i in issues]
    tagged_prs = [{"__type": "PullRequest", **p} for p in prs]

    return tagged_issues + tagged_prs
