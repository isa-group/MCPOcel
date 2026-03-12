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
        target   = node.get("target") or {}
        typename = target.get("__typename")

        if typename == "Commit":
            # Lightweight tag — points directly to a commit
            author = target.get("author") or {}
            user   = author.get("user") or {}
            yield {
                "__type":       "Tag",
                "id":           node.get("id"),
                "name":         node.get("name"),
                "date":         target.get("committedDate"),
                "tagger": {
                    "login": user.get("login"),
                    "name":  author.get("name"),
                    "email": author.get("email"),
                },
                "commit":       {"sha": target.get("oid")},
                "message":      "",
                "is_annotated": 0,
            }

        elif typename == "Tag":
            # Annotated tag — has its own metadata object
            tagger = target.get("tagger") or {}
            user   = tagger.get("user") or {}
            commit = target.get("target") or {}
            yield {
                "__type":       "Tag",
                "id":           node.get("id"),
                "name":         node.get("name"),
                "date":         tagger.get("date"),
                "tagger": {
                    "login": user.get("login"),
                    "name":  tagger.get("name"),
                    "email": tagger.get("email"),
                },
                "commit":       {"sha": commit.get("oid")},
                "message":      target.get("message", ""),
                "is_annotated": 1,
            }

        else:
            logger.debug(
                f"[fetch_tags] Skipping tag '{node.get('name')}': "
                f"unknown target type '{typename}'"
            )
            continue