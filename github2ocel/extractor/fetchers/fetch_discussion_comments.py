from typing import Generator, Dict, Any, List

from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nested
from github2ocel.extractor.graphql.queries import DISCUSSIONS_COMMENTS_QUERY
from shared.logger import get_logger

logger = get_logger(__name__)


def fetch_discussion_comments(
    client: GitHubClient,
    discussion_numbers: List[int],
    page_size: int = 50,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield all comment nodes for discussions that exceeded the embedded limit,
    fully paginated per discussion.

    Each yielded dict has '__discussion_number' injected for downstream mapping.
    Replies are nested inside each comment node under 'replies.nodes' —
    the mapper is responsible for iterating them.

    Only called for discussions in the overflow list (comments.totalCount > 50).
    """
    total_discussions = len(discussion_numbers)
    logger.info(f"--- [Fetcher] Discussion Comments for {total_discussions} discussions ---")

    total_comments = 0
    skipped        = 0

    for i, discussion_number in enumerate(int(float(n)) for n in discussion_numbers):
        if i > 0 and i % 50 == 0:
            gql = client.rate_limiter.resources["graphql"]
            logger.info(
                f"  [discussion_comments] {i}/{total_discussions} discussions | "
                f"{total_comments} comments | pts_left={gql.get('remaining', '?')}"
            )
        try:
            for comment in paginate_nested(
                client=client,
                query=DISCUSSIONS_COMMENTS_QUERY,
                parent_type="discussion",
                parent_number=discussion_number,
                nested_field="comments",
                number_var="discussionNumber",
                page_size=page_size,
            ):
                if not comment:
                    continue
                comment["__discussion_number"] = discussion_number
                comment["__type"] = "DiscussionComment"
                yield comment
                total_comments += 1

        except Exception as e:
            logger.warning(f"[fetch_discussion_comments] Failed Discussion#{discussion_number}: {e}")
            skipped += 1
            continue

    logger.info(
        f"--- [Fetcher] Discussion Comments done — "
        f"{total_comments} total, {skipped} discussions skipped ---"
    )