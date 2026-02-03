import logging
from typing import Dict, Any, List
from github2ocel.transform.builder import OCELBuilder
from github2ocel.transform.utils.ensure import ensure_user, is_pull_request
from github2ocel.transform.utils.activity import Activities

logger = logging.getLogger(__name__)

# Audit metadata (High confidence)
audit_meta = {
        "event_class": "observed",
        "source": "github_timeline_audit",
        "confidence": "high"
    }

def map_timeline_events(node: Dict[str, Any], builder: OCELBuilder, target_id: str) -> None:
    """
    Timeline event orchestrator.
    Filters and delegates each event according to its node type in GraphQL (__typename).
    """
    is_pr = is_pull_request(node)
    timeline_nodes = node.get("timelineItems", {}).get("nodes", [])

    # Dictionary of dispatchers to avoid nested IFs
    handlers = {
        "AssignedEvent": _handle_assignment,
        "UnassignedEvent": _handle_unassignment,
        "ReviewRequestedEvent": _handle_review_requested,
        "ReviewRequestRemovedEvent": _handle_review_removed,
    }

    for item in timeline_nodes:
        if not item or not item.get("createdAt"):
            continue

        typename = item.get("__typename")
        handler = handlers.get(typename)

        if handler:
            try:
                handler(item, builder, target_id, is_pr)
            except Exception as e:
                logger.warning(f"Error processing time event {typename} on {target_id}: {e}")


def _handle_assignment(item: Dict[str, Any], builder: OCELBuilder, target_id: str, is_pr: bool):
    """Handles the event of assigning a user to an issue or PR."""
    assignee_login = item.get("assignee", {}).get("login")
    assignee_id = ensure_user(builder, assignee_login)



    if assignee_id:
        activity = Activities.PR_ASSIGNED if is_pr else Activities.ISSUE_ASSIGNED
        builder.add_event(
            activity,
            item["createdAt"],
            [
                builder.rel(target_id, "target"),
                builder.rel(assignee_id, "assignee")
            ],
            audit_meta
        )
        # Persistent object relationship: defines who is currently responsible in the OCEL model.
        builder.add_object_relationship(target_id, assignee_id, "assigned_to")


def _handle_unassignment(item: Dict[str, Any], builder: OCELBuilder, target_id: str, is_pr: bool):
    """Handles the event of removing an assignment."""
    assignee_login = item.get("assignee", {}).get("login")
    assignee_id = ensure_user(builder, assignee_login)

    if assignee_id:
        activity = Activities.PR_UNASSIGNED if is_pr else Activities.ISSUE_UNASSIGNED
        builder.add_event(
            activity,
            item["createdAt"],
            [
                builder.rel(target_id, "target"),
                builder.rel(assignee_id, "assignee")
            ],
            audit_meta
        )


def _handle_review_requested(item: Dict[str, Any], builder: OCELBuilder, target_id: str, is_pr: bool):
    """Handle the review request (only applies to PRs)."""
    if not is_pr: return

    reviewer_login = item.get("requestedReviewer", {}).get("login")
    reviewer_id = ensure_user(builder, reviewer_login)

    if reviewer_id:
        builder.add_event(
            Activities.PR_REVIEW_REQUESTED,
            item["createdAt"],
            [
                builder.rel(target_id, "target"),
                builder.rel(reviewer_id, "reviewer")
            ],
            audit_meta
        )
        builder.add_object_relationship(target_id, reviewer_id, "review_requested_from")


def _handle_review_removed(item: Dict[str, Any], builder: OCELBuilder, target_id: str, is_pr: bool):
    """Handles the cancellation of a review request."""
    if not is_pr: return

    reviewer_login = item.get("requestedReviewer", {}).get("login")
    reviewer_id = ensure_user(builder, reviewer_login)

    if reviewer_id:
        builder.add_event(
            Activities.PR_REVIEW_REQUEST_REMOVED,
            item["createdAt"],
            [
                builder.rel(target_id, "target"),
                builder.rel(reviewer_id, "reviewer")
            ],
            audit_meta
        )