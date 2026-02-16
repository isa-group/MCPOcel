from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from shared.logger import get_logger

logger = get_logger(__name__)

def fetch_commits_graphql(
    client: GitHubClient,
    page_size: int = 50
) -> Generator[Dict[str, Any], None, None]:
    """
    Extract commits using GraphQL.
    """
    since_iso, _ = client.time_window_iso
    
    query = """
    query($owner: String!, $repo: String!, $pageSize: Int!, $cursor: String, $since: GitTimestamp) {
      repository(owner: $owner, name: $repo) {
        defaultBranchRef {
          target {
            ... on Commit {
              # since requires GitTimestamp
              history(first: $pageSize, after: $cursor, since: $since) {
                pageInfo { hasNextPage, endCursor }
                nodes {
                  oid       # SHA
                  message
                  committedDate
                  changedFilesIfAvailable
                  additions
                  deletions
                  author {
                    name
                    email
                    date
                    user { 
                      login 
                      id          # Global Node ID (User)
                    }
                  }
                  committer {
                    name
                    date
                    user {
                      login
                      id
                    }
                  }
                  signature { isValid }
                  parents(first: 5) { totalCount }
                  checkSuites(first: 1) {
                    nodes {
                      conclusion
                      status
                    }
                  }
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
        "cursor": None,
        "since": since_iso
    }

    logger.info(f"--- Fetching Commits via GraphQL (Page Size: {page_size}) ---")
    
    total_fetched = 0
    has_next = True

    while has_next:
        try:
            payload = client.graphql(query, variables)
            
            repo_data = payload.get("data", {}).get("repository", {})
            ref = repo_data.get("defaultBranchRef")
            
            if not ref:
                logger.warning("No default branch found via GraphQL.")
                break

            history = ref.get("target", {}).get("history", {})
            nodes = history.get("nodes", [])
            page_info = history.get("page_info", history.get("pageInfo", {}))

            if not nodes:
                break

            for node in nodes:
                node["__type"] = "Commit"
                yield node
                total_fetched += 1

            has_next = page_info.get("hasNextPage", False)
            variables["cursor"] = page_info.get("endCursor")

            if total_fetched % 100 == 0:
                logger.info(f"Commits (GraphQL): {total_fetched}...")

        except Exception as e:
            logger.error(f"Error in GraphQL commits pagination: {e}")
            break

    logger.info(f"Commits extraction completed. Total: {total_fetched}")