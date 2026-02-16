import uuid
import logging
from typing import Dict, Any
from github2ocel.transform.builder import OCELBuilder
from github2ocel.transform.utils.ensure import ensure_user, ensure_team
from github2ocel.transform.utils.helper import safe_timestamp, calculate_duration
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.model.models import Event, ObjectInstance

logger = logging.getLogger(__name__)

def map_timeline_events(node: Dict[str, Any], builder: OCELBuilder, target_id: str, repo_id: str, is_pr: bool) -> None:
    """
    Timeline event orchestrator.
    Maps assignments, reviews requested, and other timeline items.
    """
    # Calculate is_pr once here to pass it down
    base_time = node.get("createdAt") # root object (Issue/PR)
    timeline_nodes = node.get("timelineItems", {}).get("nodes", [])

    handlers = {
        "AssignedEvent": _handle_assignment,
        "UnassignedEvent": _handle_unassignment,
        "ReviewRequestedEvent": _handle_review_requested,
        "ReviewRequestRemovedEvent": _handle_review_removed,
    }

    for item in timeline_nodes:
        if not item or not item.get("createdAt"): continue

        typename = item.get("__typename")
        handler = handlers.get(typename)

        if handler:
            try:
                # Dispatch with is_pr explicitly passed
                handler(item, builder, target_id, is_pr, repo_id, base_time)
            except Exception as e:
                logger.warning(f"Error processing timeline {typename} on {target_id}: {e}")


def _handle_assignment(
        item: Dict[str, Any],
        builder: OCELBuilder,
        target_id: str,
        is_pr: bool,
        repo_id: str,
        base_time: str):

    ts = safe_timestamp(item["createdAt"])
    assignee_login = item.get("assignee", {}).get("login")
    assignee_id = ensure_user(builder, repo_id, assignee_login, timestamp=ts)

    if assignee_id:
        time_to_assign = calculate_duration(base_time, item["createdAt"])
        activity = Activities.PR_ASSIGNED if is_pr else Activities.ISSUE_ASSIGNED

        # Create Evento
        evt = Event(
            event_id=str(uuid.uuid4()),
            event_type=activity,
            time=ts,
            attributes={
                "source": "timeline",
                "assignment_latency_seconds": time_to_assign
            }
        )
        evt.add_rel(target_id, "target")
        evt.add_rel(assignee_id, "assignee")

        builder.insert_event(evt)

        # Issue -> User
        proxy_target = ObjectInstance(object_id=target_id, object_type="Unknown")
        proxy_target.add_rel(target_id=assignee_id, qualifier="assigned_to")

        builder.insert_object(proxy_target)


def _handle_unassignment(
        item: Dict[str, Any],
        builder: OCELBuilder,
        target_id: str,
        is_pr: bool,
        repo_id: str,
        base_time: str):

    ts = safe_timestamp(item["createdAt"])
    assignee_login = item.get("assignee", {}).get("login")
    assignee_id = ensure_user(builder, repo_id, assignee_login, timestamp=ts)

    if assignee_id:
        duration = calculate_duration(base_time, item["createdAt"])
        activity = Activities.PR_UNASSIGNED if is_pr else Activities.ISSUE_UNASSIGNED

        evt = Event(
            event_id=str(uuid.uuid4()),
            event_type=activity,
            time=ts,
            attributes={
                "source": "timeline",
                "lifecycle_duration_seconds": duration
            }
        )
        evt.add_rel(target_id, "target")
        evt.add_rel(assignee_id, "unassigned_user")

        builder.insert_event(evt)

def _handle_review_requested(
        item: Dict[str, Any],
        builder: OCELBuilder,
        target_id: str,
        is_pr: bool,
        repo_id: str,
        base_time: str):

    if not is_pr: return
    ts = safe_timestamp(item["createdAt"])

    reviewer_node = item.get("requestedReviewer")
    if not reviewer_node:
        logger.debug(f"ReviewRequestedEvent on {target_id} has no requestedReviewer data")
        return
    
    reviewer_id = None
    typename = reviewer_node.get("__typename")

    if typename == "User":
        login = reviewer_node.get("login")
        if login:
            reviewer_id = ensure_user(builder, repo_id, login, timestamp=ts)
    elif typename == "Team":
        reviewer_id = ensure_user(builder, repo_id, reviewer_login, timestamp=ts)

    if reviewer_id:
        time_to_ready = calculate_duration(base_time, item["createdAt"])
        reviewer_login = reviewer_node.get("login") or reviewer_node.get("name", "Unknown")
        
        evt = Event(
            event_id=str(uuid.uuid4()),
            event_type=Activities.PR_REVIEW_REQUESTED,
            time=ts,
            attributes={
                "time_to_ready_seconds": time_to_ready,
                "reviewer_login": reviewer_login
            }
        )
        evt.add_rel(target_id, "target")
        evt.add_rel(reviewer_id, "requested_reviewer")

        builder.insert_event(evt)

        # PR -> Reviewer
        proxy_target = ObjectInstance(object_id=target_id, object_type="Unknown")
        proxy_target.add_rel(target_id=reviewer_id, qualifier="review_requested_from")

        builder.insert_object(proxy_target)


def _handle_review_removed(
        item: Dict[str, Any],
        builder: OCELBuilder,
        target_id: str,
        is_pr: bool,
        repo_id: str,
        base_time: str):

    if not is_pr: return
    ts = safe_timestamp(item["createdAt"])

    reviewer_node = item.get("requestedReviewer")

    if not reviewer_node:
        return
    reviewer_id = None
    typename = reviewer_node.get("__typename")
    
    if typename == "User":
        login = reviewer_node.get("login")
        if login:
            reviewer_id = ensure_user(builder, repo_id, login, timestamp=ts)
    elif typename == "Team":
        reviewer_id = ensure_team(builder, repo_id, reviewer_node)
    else:
        # Fallback if __typename is not present
        reviewer_name = reviewer_node.get("login") or reviewer_node.get("name")
        if reviewer_name:
            reviewer_id = ensure_user(builder, repo_id, reviewer_name, timestamp=ts)

    if reviewer_id:
        removal_latency = calculate_duration(base_time, item["createdAt"])
        evt = Event(
            event_id=str(uuid.uuid4()),
            event_type=Activities.PR_REVIEW_REQUEST_REMOVED,
            time=ts,
            attributes={
                "seconds_since_creation": removal_latency,
                "reason": "manual_removal",
                "reviewer_type": typename or "Unknown"
            }
        )
        evt.add_rel(target_id, "target")
        evt.add_rel(reviewer_id, "removed_reviewer")

        builder.insert_event(evt)
