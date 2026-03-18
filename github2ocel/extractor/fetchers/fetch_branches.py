from typing import Generator, Dict, Any

from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nodes
from github2ocel.extractor.graphql.queries import BRANCHES_QUERY
from shared.logger import get_logger

logger = get_logger(__name__)


def fetch_branches(
    client: GitHubClient,
    page_size: int = 100,
    total: int = 0,
) -> Generator[Dict[str, Any], None, None]:
    """Yield all branch nodes from the repository via GraphQL.

    GraphQL refs(refPrefix: 'refs/heads/') returns branchProtectionRule and
    HEAD commit metadata in a single paginated request — no per-branch REST
    calls needed.
    """
    logger.info(f"--- [Fetcher] Branches (pageSize={page_size}) ---")

    for node in paginate_nodes(
        client=client,
        query=BRANCHES_QUERY,
        node_type="refs",
        variables={"pageSize": page_size},
        total=total,
        label="branches",
    ):
        node["__type"] = "Branch"
        yield node
