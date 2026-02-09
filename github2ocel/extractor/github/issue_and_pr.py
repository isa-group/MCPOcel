from typing import Dict, Any, Generator

from github2ocel.client.github_client import GitHubClient
from github2ocel.extractor.graphql.paginator import paginate_nodes
from github2ocel.extractor.graphql.queries import ISSUES_QUERY, PRS_QUERY
from shared.logger import  get_logger

logger = get_logger(__name__)

def fetch_github_data(client: GitHubClient) -> Generator[Dict[str, Any], None, None]:
    """
    Fetches Issues and PRs using the robust GitHubClient.
    Yields items one by one to save memory.
    """
    logger.info("--- Fetching Issues & PRs (GraphQL) ---")

    # Phase A: Issues
    issue_gen = paginate_nodes(
        client=client,
        query=ISSUES_QUERY,
        node_type="issues",
    )

    for node in issue_gen:
        node["__type"] = "Issue"
        yield node

    # Phase B: Pull Requests
    pr_gen = paginate_nodes(
        client=client,
        query=PRS_QUERY,
        node_type="pullRequests",
    )

    for node in pr_gen:
        node["__type"] = "PullRequest"
        yield node