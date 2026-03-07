from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nodes
from github2ocel.extractor.graphql.queries import ISSUES_QUERY
from shared.logger import get_logger

logger = get_logger(__name__)


def fetch_issues(
    client: GitHubClient,
    page_size: int = 50,
    total: int = 0,
    since: str = None,
) -> Generator[Dict[str, Any], None, None]:
    """Yield all issue nodes. Timeline is NOT included here."""

    logger.info(f"--- [Fetcher] Issues (pageSize={page_size}) ---")

    variables = {"pageSize": page_size}

    if since:
        variables["since"] = since

    for node in paginate_nodes(
        client=client,
        query=ISSUES_QUERY,
        node_type="issues",
        variables=variables,
        total=total,
        label="issues",
    ):
        node["__type"] = "Issue"
        yield node