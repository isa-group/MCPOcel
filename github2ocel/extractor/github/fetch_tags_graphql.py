from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from shared.logger import get_logger

logger = get_logger(__name__)

def fetch_tags_graphql(
    client: GitHubClient,
    page_size: int = 100
) -> Generator[Dict[str, Any], None, None]:
    """
    Extract tags with their actual date using GraphQL.
    Automatically determine whether it is a Lightweight or Annotated Tag.
    """
    
    # Tag vs Commit
    query = """
    query($owner: String!, $repo: String!, $pageSize: Int!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        refs(refPrefix: "refs/tags/", first: $pageSize, after: $cursor, orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) {
          pageInfo { hasNextPage, endCursor }
          nodes {
            name
            target {
              __typename
              ... on Commit {
                oid
                committedDate
                author { user { login id } }
              }
              ... on Tag {
                oid
                tagger {
                  date
                  user { login id }
                }
                target {
                  ... on Commit {
                    oid # commit that the tag points to
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
        "cursor": None
    }

    logger.info(f"--- Fetching Tags via GraphQL (Page Size: {page_size}) ---")
    
    total_fetched = 0
    has_next = True

    while has_next:
        try:
            payload = client.graphql(query, variables)
            
            repo_data = payload.get("data", {}).get("repository", {})
            refs = repo_data.get("refs", {})
            nodes = refs.get("nodes", [])
            page_info = refs.get("pageInfo", {})

            if not nodes:
                break

            for node in nodes:
                target = node.get("target", {})
                typename = target.get("__typename")
                
                final_date = None
                commit_sha = None

                if typename == "Commit":
                    # Lightweight Tag: commit date
                    final_date = target.get("committedDate")
                    commit_sha = target.get("oid")
                
                elif typename == "Tag":
                    # Annotated Tag: tagger date
                    final_date = target.get("tagger", {}).get("date")
                    # El commit real está un nivel más abajo
                    commit_sha = target.get("target", {}).get("oid")

                tag_flat = {
                    "name": node.get("name"),
                    "date": final_date,
                    "commit": {
                        "sha": commit_sha
                    },
                    "__type": "Tag"
                }
                
                yield tag_flat
                total_fetched += 1

            has_next = page_info.get("hasNextPage", False)
            variables["cursor"] = page_info.get("endCursor")

        except Exception as e:
            logger.error(f"Error in GraphQL tags pagination: {e}")
            break

    logger.info(f"Tags extraction completed. Total: {total_fetched}")