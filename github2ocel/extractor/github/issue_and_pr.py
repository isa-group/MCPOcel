from typing import Dict, Any, Generator

from github2ocel.client.github_client import GitHubClient
from github2ocel.extractor.graphql.paginator import paginate_nodes
from github2ocel.extractor.graphql.queries import ISSUES_QUERY, PRS_QUERY, DISCUSSIONS_QUERY
from shared.logger import  get_logger

logger = get_logger(__name__)

def fetch_github_data(
        client: GitHubClient,
        variables: Dict[str, Any],
        stats: Dict[str, int]
        ) -> Generator[Dict[str, Any], None, None]:
    """
    Fetches Issues and PRs using the robust GitHubClient.
    Yields items one by one to save memory.
    """
    logger.info("--- Fetching Issues & PRs (GraphQL) ---")

    if "owner" not in variables:
        variables["owner"] = client.owner
    if "repo" not in variables:
        variables["repo"] = client.repo

    # Phase A: Issues
    issue_gen = paginate_nodes(
        client=client,
        query=ISSUES_QUERY,
        variables=variables,
        node_type="issues",
    )

    for node in issue_gen:
        stats["issues"] += 1
        node["__type"] = "Issue"
        yield node

    # Phase B: Pull Requests
    pr_gen = paginate_nodes(
        client=client,
        query=PRS_QUERY,
        variables=variables,
        node_type="pullRequests",
    )

    for node in pr_gen:
        stats["prs"] += 1
        node["__type"] = "PullRequest"
        yield node

    # Phase C: Discussions
    disc_variables = {
        k: v for k, v in variables.items()
          if k in ("owner", "repo", "pageSize")
    } # Only pass relevant variables to the discussions query

    discussion_gen = paginate_nodes(
        client=client,
        query=DISCUSSIONS_QUERY,
        variables=disc_variables,
        node_type="discussions"
    )
    for node in discussion_gen:
        stats["discussions"] += 1
        node["__type"] = "Discussion"
        yield node