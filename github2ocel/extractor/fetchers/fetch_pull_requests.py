from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nodes
from github2ocel.extractor.graphql.queries import PULL_REQUESTS_QUERY

from shared.logger import get_logger

logger = get_logger(__name__)

def fetch_pull_requests(
    client: GitHubClient,
    page_size: int = 50,
    total: int = 0,
    since: str = None,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield all PR base nodes.
    Safe at pageSize=50: only scalars + tiny connections (no commits, no comments, no CI).
    """
    logger.info(f"--- [Fetcher] Pull Requests (pageSize={page_size}) ---")

    variables = {"pageSize": page_size}

    if since:
        variables["since"] = since

    for node in paginate_nodes(
        client=client,
        query=PULL_REQUESTS_QUERY,
        node_type="pullRequests",
        variables=variables,
        total=total,
        label="prs",
    ):
        node["__type"] = "PullRequest"
        yield node
