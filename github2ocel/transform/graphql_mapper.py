import logging
from typing import Dict, Any

from .mappers.issues_prs import process_base_node, map_main_events, map_management_context #, map_review_threads
from .mappers.lifecycle import map_lifecycle_events
from .mappers.timeline import map_timeline_events
from .utils.ensure import get_node_type, is_pull_request
from .mappers.devops import map_devops_events

logger = logging.getLogger(__name__)

def process_issue_node(node: Dict[str, Any], builder: Any, repo_id: str) -> None:
    """
    Lead orchestrator for GraphQL nodes.
    """

    try:
        # Validation of minimum required fields
        node_type = get_node_type(node)
        node_number = node.get("number")
        is_pr = is_pull_request(node)

        if node_number is None:
            raise KeyError("number")
        if not node.get("createdAt"):
            raise KeyError("createdAt")

        # 1. Create the object (Issue or PR)
        obj_id, is_pr = process_base_node(node, builder, repo_id)

        # 2. Issue/PR to Milestone
        map_management_context(node, builder, obj_id)

        # 3. Record main events (Open/Close/Merge)
        map_main_events(node, builder, repo_id, obj_id, is_pr)

        # 4. Process interactions (Tags, Comments, Reviews)
        map_lifecycle_events(node, builder, repo_id, obj_id)

        # 5. Process workflow (Assignments, Review Requests)
        map_timeline_events(node, builder, obj_id)

        # 6. Reviews thread
        # map_review_threads(node, builder, obj_id)

        # . DevOps (Only PRs)
        if is_pr:
            map_devops_events(node, builder, obj_id)

    except Exception as e:
        logger.error(f"Error en {node_type} #{node_number}: {e}")
    except ValueError as value:
        # Semantic errors (e.g. unknown node type)
        logger.warning(f"Skipping node due to contract violation: {value}")

    except KeyError as key:
        # Structure errors (e.g., GitHub did not return an expected field)
        logger.error(f"Data structure error: Missing mandatory field {key} in node {node.get('id', 'unknown')}")

    except Exception as e:
        # Unexpected errors (bugs in the code, memory problems, etc.)
        logger.critical(f"Unexpected error processing {node_type} #{node_number}: {e}", exc_info=True)