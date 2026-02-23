import logging
from typing import Dict, Any

from shared.ocel.builder import OCELBuilder
from .mappers.issues_prs import process_base_node, map_main_events, map_management_context #, map_review_threads
from .mappers.lifecycle import map_lifecycle_events
from .mappers.timeline import map_timeline_events

logger = logging.getLogger(__name__)

def process_issue_node(node: Dict[str, Any], builder: OCELBuilder, repo_id: str, node_type: str) -> None:
    """
    Main orchestrator for GraphQL nodes.
    Receives a node (Issue or PR) and coordinates the extraction of all its events and objects.
    """
    is_pr = node_type == "PullRequest"
    existing_issues = {} 
    try:
        # 1. Create the object (Issue or PR)
        obj_id = process_base_node(node, builder, repo_id, is_pr)
        if not is_pr:
            existing_issues[node["number"]] = obj_id

        # 2. Issue/PR to Milestone
        map_management_context(node, builder, obj_id)

        # 3. Record main events (Open/Close/Merge)
        map_main_events(node, builder, repo_id, obj_id, is_pr)

        # 4. Process interactions (Tags, Comments, Reviews)
        map_lifecycle_events(node, builder, repo_id, obj_id, is_pr)

        # 5. Process workflow (Assignments, Review Requests)
        map_timeline_events(node, builder, obj_id, repo_id, is_pr)

        # 6. Reviews thread
        # map_review_threads(node, builder, obj_id)

    except ValueError as value:
        # Semantic errors (e.g. unknown node type)
        logger.warning(f"Skipping node due to contract violation: {value}")

    except KeyError as key:
        # Structure errors (e.g., GitHub did not return an expected field)
        logger.error(f"Data structure error: Missing mandatory field {key} in node {node.get('id', 'unknown')}")

    except Exception as e:
        # Unexpected errors (bugs in the code, memory problems, etc.)
        logger.critical(f"Unexpected error processing Issue: {e}", exc_info=True)