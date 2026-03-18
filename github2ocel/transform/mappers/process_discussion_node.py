import logging
from typing import Dict, Any
from shared.ocel.builder import OCELBuilder
from github2ocel.transform.mappers.process_discussion import process_discussion
from github2ocel.transform.mappers.process_comment import map_discussion_comment

logger = logging.getLogger(__name__)

def process_discussion_node(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Orchestrate the extraction of a Discussion and all its comments.
    """
    try:
        # Process the main Discussion and its base events
        discussion_id = process_discussion(node, builder, repo_id)

        if not discussion_id:
            logger.warning(f"[process_discussion_node] Failed to process discussion #{node.get('number')}. Skipping.")
            return

        # Process the comments associated with this discussion
        comments_data = node.get("comments", {})
        if comments_data and "nodes" in comments_data:
            for comment in comments_data["nodes"]:
                if not comment:
                    continue
                comment_id = map_discussion_comment(comment, builder, repo_id, discussion_id)
                # Map replies (second-level comments in discussions)
                for reply in (comment.get("replies") or {}).get("nodes", []):
                    if reply:
                        map_discussion_comment(
                            reply, builder, repo_id, discussion_id,
                            parent_comment_id=comment.get("id")
                        )

    except Exception as e:
        logger.critical(f"Unexpected error processing Discussion: {e}", exc_info=True)