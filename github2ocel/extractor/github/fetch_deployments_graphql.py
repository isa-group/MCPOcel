from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from shared.logger import get_logger

logger = get_logger(__name__)

def fetch_deployments_graphql(
    client: GitHubClient,
    page_size: int = 50
) -> Generator[Dict[str, Any], None, None]:
    """
    Extract Deployments and Statuses with GraphQL
    """
    
    query = """
    query($owner: String!, $repo: String!, $pageSize: Int!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        deployments(first: $pageSize, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
          pageInfo { hasNextPage, endCursor }
          nodes {
            id # Global ID
            databaseId # ID Entero
            environment
            state
            description
            createdAt
            updatedAt
            
            commit {
              oid
            }
            
            creator {
              login
              ... on User { id }
              ... on Bot { id }
            }
            statuses(first: 5) {
              nodes {
                state
                description
                createdAt
                creator {
                  login
                  ... on User { id }
                }
              }
            }
          }
        }
      }
    }
    """

    variables = {
        "owner": client.owner,
        "repo": client.repo,
        "pageSize": page_size,
        "cursor": None
    }

    logger.info(f"--- Fetching Deployments via GraphQL (Page Size: {page_size}) ---")
    
    total_fetched = 0
    has_next = True

    while has_next:
        try:
            payload = client.graphql(query, variables)
            
            repo_data = payload.get("data", {}).get("repository", {})
            deps_wrapper = repo_data.get("deployments", {})
            nodes = deps_wrapper.get("nodes", [])
            page_info = deps_wrapper.get("pageInfo", {})

            if not nodes:
                break

            for node in nodes:
                node["__type"] = "Deployment"
                yield node
                total_fetched += 1

            has_next = page_info.get("hasNextPage", False)
            variables["cursor"] = page_info.get("endCursor")

            if total_fetched % 100 == 0:
                logger.info(f"Deployments (GraphQL): {total_fetched}...")

        except Exception as e:
            logger.error(f"Error in GraphQL deployments pagination: {e}")
            break

    logger.info(f"Deployments extraction completed. Total: {total_fetched}")