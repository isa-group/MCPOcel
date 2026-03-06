from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nodes
from github2ocel.extractor.graphql.queries import TAGS_QUERY
from shared.logger import get_logger

logger = get_logger(__name__)

def fetch_tags(
    client: GitHubClient,
    page_size: int = 100,
    total: int = 0,
) -> Generator[Dict[str, Any], None, None]:

    logger.info(f"--- [Fetcher] Tags (pageSize={page_size}) ---")

    for node in paginate_nodes(
        client=client,
        query=TAGS_QUERY,
        node_type="refs",
        variables={"pageSize": page_size},
        total=total,
        label="tags",
    ):
        target = node.get("target") or {}
        typename = target.get("__typename")

        if typename == "Commit":
            # Lightweight tag — points directly to a commit
            author_node = (target.get("author") or {})
            user_node   = author_node.get("user") or {}
            login       = user_node.get("login")

            yield {
                "__type":     "Tag",
                "name":       node.get("name"),
                "date":       target.get("committedDate"),
                "tagger":     {"login": login} if login else None,
                "commit":     {"sha": target.get("oid")},
                "message":    "",
                "is_annotated": 0,
            }

        elif typename == "Tag":
            # Annotated tag — has its own metadata object
            tagger_node  = target.get("tagger") or {}
            user_node    = tagger_node.get("user") or {}
            login        = user_node.get("login")
            commit_sha   = (target.get("target") or {}).get("oid")

            yield {
                "__type":     "Tag",
                "name":       node.get("name"),
                "date":       tagger_node.get("date"),
                "tagger":     {"login": login} if login else None,
                "commit":     {"sha": commit_sha},
                "message":    target.get("message", ""),
                "is_annotated": 1,
            }

        else:
            # Unknown target type — skip silently
            logger.debug(f"[fetch_tags] Skipping tag '{node.get('name')}': unknown target type '{typename}'")
            continue