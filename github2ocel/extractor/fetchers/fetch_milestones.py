from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nodes
from github2ocel.extractor.graphql.queries import MILESTONES_QUERY
from shared.logger import get_logger

logger = get_logger(__name__)

def fetch_milestones(
    client: GitHubClient,
    page_size: int = 100,
    total: int = 0,
) -> Generator[Dict[str, Any], None, None]:
    """Yield all milestone nodes from the repository."""

    logger.info(f"--- [Fetcher] Milestones (pageSize={page_size}) ---")

    variables = {"pageSize": page_size}
    count = 0

    for node in paginate_nodes(
        client=client,
        query=MILESTONES_QUERY,
        node_type="milestones",
        variables=variables,
        total=total,
        label="milestones",
    ):
        node["__type"] = "Milestone"
        yield node
        count += 1

    logger.info(f"--- [Fetcher] Milestone done — {count} ---")
