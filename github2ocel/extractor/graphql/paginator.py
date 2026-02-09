import logging
from typing import Generator, Dict, Any, Optional

from github2ocel.client.github_client import GitHubClient

logger = logging.getLogger(__name__)

def paginate_nodes(
    client: GitHubClient,
    query: str,
    node_type: str,           # "issues", "pullRequests"
    page_size: Optional[int] = None,
) -> Generator[Dict[str, Any], None, None]:
    """
    Generic pagination engine for GraphQL.
    Handles GitHub's nested response (data -> repository -> node_type).
    """

    cursor = None
    current_page = 1
    total_nodes = 0

    max_pages = client.max_pages
    final_page_size = page_size if page_size is not None else getattr(client, "graphql_per_page", 50)

    logger.info(f"Starting GraphQL pagination for {node_type} (Page Size: {final_page_size})...")

    while True:
        # 1. Control de Límite de Páginas
        if max_pages and current_page > max_pages:
            logger.info(f"Reached max page limit ({max_pages}) for {node_type}")
            break

        variables = {
            "owner": client.owner,
            "repo": client.repo,
            "cursor": cursor,
            "pageSize": final_page_size,
        }

        try:
            response = client.graphql(query, variables)

            data_content = response.get("data", response)

            if data_content is None:
                data_content = {}

            # Repository
            repo_data = data_content.get("repository")

            if not repo_data:
                logger.error(f"CRITICAL: 'repository' missing for {node_type}.")
                logger.error(f"Keys found in response: {list(response.keys())}")
                if "errors" in response:
                    logger.error(f"Errors in payload: {response['errors']}")
                break

            # Extract
            container = repo_data.get(node_type, {})
            nodes = container.get("nodes", [])

            if nodes:
                count = 0
                for node in nodes:
                    if node: # null filter
                        yield node
                        count += 1
                total_nodes += count

            # Cursor
            page_info = container.get("pageInfo", {})
            has_next = page_info.get("hasNextPage", False)
            next_cursor = page_info.get("endCursor")

            if not has_next or not next_cursor:
                logger.info(f"Pagination completed for {node_type}. Total: {total_nodes}")
                break

            if next_cursor == cursor:
                logger.warning(f"Cursor stuck at {cursor}. Stopping.")
                break

            cursor = next_cursor
            current_page += 1

            if current_page % 5 == 0:
                logger.info(f"{node_type}: Processed page {current_page}...")

        except Exception as e:
            logger.error(f"Failed to fetch page {current_page} of {node_type}: {e}")
            raise e

    logger.info(f"Pagination completed for {node_type}. Total extracted: {total_nodes}")