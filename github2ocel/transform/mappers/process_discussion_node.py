import logging
from typing import Dict, Any
from shared.ocel.builder import OCELBuilder
from github2ocel.transform.mappers.process_discussion import process_discussion
from github2ocel.transform.mappers.process_discussion_comment import process_discussion_comment

logger = logging.getLogger(__name__)

def process_discussion_node(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Orchestrate the extraction of a Discussion and all its comments.
    """
    try:
        # Process the main Discussion and its base events
        discussion_id = process_discussion(node, builder, repo_id)

        if not discussion_id:
            return # abort this node

        # Process the comments associated with this discussion
        comments_data = node.get("comments", {})
        if comments_data and "nodes" in comments_data:
            for comment in comments_data["nodes"]:
                if not comment:
                    continue
                process_discussion_comment(comment, builder, repo_id, discussion_id)

    except Exception as e:
        logger.critical(f"Unexpected error processing Discussion: {e}", exc_info=True)