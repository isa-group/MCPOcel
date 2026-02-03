import logging
from typing import List, Dict, Any, Optional

from github2ocel.config.settings import APIConfig
from .graphql import graphql_query

logger = logging.getLogger(__name__)

def paginate_nodes(
    query: str,
    node_type: str,
    owner: str,
    repo: str,
    token: str,
    api_config: APIConfig,
    pages: Optional[int] = None,
    page_size: int = 50,
) -> List[Dict[str, Any]]:
    nodes_all = []
    cursor = None
    current_page = 1
    target_pages = pages if pages is not None else api_config.max_pages

    while True:
        if target_pages and current_page > target_pages:
            break

        variables = {
            "owner": owner,
            "repo": repo,
            "cursor": cursor,
            "pageSize": page_size,
        }

        data = graphql_query(query, variables, token, api_config)
        repo_data = data.get("repository", {})
        container = repo_data.get(node_type, {})

        nodes = [n for n in container.get("nodes", []) if n]
        nodes_all.extend(nodes)

        page_info = container.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break

        cursor = page_info.get("endCursor")
        current_page += 1

        logger.info(f"{node_type}: fetched page {current_page-1}")

    logger.info(f"{node_type}: fetched {len(nodes_all)} total")
    return nodes_all
