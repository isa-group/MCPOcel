from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nodes
from github2ocel.extractor.graphql.queries import DEPLOYMENTS_QUERY
from shared.logger import get_logger

logger = get_logger(__name__)


def fetch_deployments(
    client: GitHubClient,
    page_size: int = 40,
) -> Generator[Dict[str, Any], None, None]:
    """Yield deployment nodes with their status history."""
    logger.info("--- [Fetcher] Deployments ---")

    for node in paginate_nodes(
        client=client,
        query=DEPLOYMENTS_QUERY,
        node_type="deployments",
        variables={"pageSize": page_size},
    ):
        node["__type"] = "Deployment"
        yield node
