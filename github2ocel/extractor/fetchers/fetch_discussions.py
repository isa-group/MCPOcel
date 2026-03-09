from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nodes
from github2ocel.extractor.graphql.queries import DISCUSSIONS_QUERY
from shared.logger import get_logger

logger = get_logger(__name__)

def fetch_discussions(
    client: GitHubClient,
    page_size: int = 50,
) -> Generator[Dict[str, Any], None, None]:
    logger.info("--- [Fetcher] Discussions ---")

    for node in paginate_nodes(
        client=client,
        query=DISCUSSIONS_QUERY,
        node_type="discussions",
        variables={"pageSize": page_size},
    ):
        node["__type"] = "Discussion"
        yield node