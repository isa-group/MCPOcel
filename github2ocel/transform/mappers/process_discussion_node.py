from typing import Dict, Any

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.mappers.process_discussion import process_discussion
from github2ocel.transform.mappers.process_comment import map_discussion_comment
from shared.logger import get_logger
from github2ocel.transform.utils.helper import make_id

logger = get_logger(__name__)


def process_discussion_node(
    node: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
) -> bool:
    """
    Orchestrate the extraction of a Discussion and its embedded comments.

    Returns True if the discussion had more comments than the embedded limit
    (comments.pageInfo.hasNextPage = True), signalling the orchestrator to
    add this discussion number to the overflow list for Phase 7b pagination.

    Replies embedded within each comment are always mapped here regardless
    of overflow — the reply embed limit (first: 15) is sufficient for most
    discussions. Replies with hasNextPage are not currently paginated.
    """
    try:
        discussion_id = process_discussion(node, builder, repo_id)

        if not discussion_id:
            logger.warning(
                f"[process_discussion_node] Failed to process "
                f"discussion #{node.get('number')}. Skipping."
            )
            return False

        comments_data = node.get("comments") or {}
        has_overflow  = (comments_data.get("pageInfo") or {}).get("hasNextPage", False)

        for comment in (comments_data.get("nodes") or []):
            if not comment:
                continue
            comment_id = map_discussion_comment(comment, builder, repo_id, discussion_id)

            # Map replies (second-level comments)
            for reply in (comment.get("replies") or {}).get("nodes") or []:
                if reply:
                    map_discussion_comment(
                        reply, builder, repo_id, discussion_id,
                        parent_comment_id=comment.get("id"),
                    )

        return has_overflow

    except Exception as e:
        logger.error(
            f"[process_discussion_node] Unexpected error processing "
            f"Discussion #{node.get('number')}: {e}",
            exc_info=True,
        )
        return False


def process_discussion_comment(
    comment: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
) -> None:
    """
    Map a single paginated discussion comment (+ its replies) to OCEL objects.

    Called from Phase 7b with fully paginated comment nodes from
    fetch_discussion_comments. The comment dict must have
    '__discussion_number' injected by the fetcher.
    """
    discussion_number = comment.get("__discussion_number")
    if not discussion_number:
        return

    discussion_id = make_id(repo_id, "discussion", discussion_number)
    if not builder.object_exists(discussion_id):
        return

    comment_id = map_discussion_comment(comment, builder, repo_id, discussion_id)

    for reply in (comment.get("replies") or {}).get("nodes") or []:
        if reply:
            map_discussion_comment(
                reply, builder, repo_id, discussion_id,
                parent_comment_id=comment.get("id"),
            )