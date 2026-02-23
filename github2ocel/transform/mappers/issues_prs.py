import uuid
import logging
from typing import Dict, Any, Tuple
from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, safe_timestamp
from github2ocel.transform.utils.ensure import ensure_user
from github2ocel.transform.utils.activity import Activities
from shared.ocel.model.models import ObjectInstance, Event
from github2ocel.utils.is_pull_request import is_pull_request

logger = logging.getLogger(__name__)

def process_base_node(node: Dict[str, Any], builder: OCELBuilder, repo_id: str, is_pr: bool) -> Tuple[str, bool]:
    """
    Creates the base object (Issue or PullRequest) and returns its ID and type.
    """

    created_at = safe_timestamp(node.get("createdAt"))

    try:
        obj_id = make_id(repo_id, "issue", node["number"])
    except (KeyError, ValueError) as e:
        logger.error(f"Error generating ID for {repo_id}: {e}")
        raise

    attrs = {
        "time": created_at,
        "number": int(node["number"]),
        "title": node.get("title", "")[:255],
        "state": node.get("state", "OPEN"),
        "url": node.get("url", ""),
        "updated_at": safe_timestamp(node.get("updatedAt")),
        "body_text": node.get("bodyText", "")[:10000],
        "body_length": len(node.get("body", "") or ""),

        # 3. Metadata Social
        "reactions_count": node.get("reactions", {}).get("totalCount", 0)
    }

    if is_pr:
        attrs.update({
            "merged": int(node.get("merged", False)),
            "merged_at": safe_timestamp(node.get("mergedAt")),
            "head_ref": node.get("headRefName", ""),
            "base_ref": node.get("baseRefName", ""),
            "is_draft": int(node.get("isDraft", False)),
            "additions": node.get("additions", 0),
            "deletions": node.get("deletions", 0),
            "changed_files": node.get("changedFiles", 0),
            "total_changes": node.get("additions", 0) + node.get("deletions", 0),
            "participants_count": node.get("participants", {}).get("totalCount", 0)
        })
    else:
        # Exclusive attributes of Issues
        attrs.update({
            "state_reason": node.get("stateReason", "Ns/Nc") # COMPLETED vs NOT_PLANNED
        })

    node_type = "PullRequest" if is_pr else "Issue"

    obj = ObjectInstance(object_id=obj_id, object_type=node_type)
    obj.add_snapshot(time=created_at, attributes=attrs)
    obj.add_rel(target_id=repo_id, qualifier="contained_in")

    builder.insert_object(obj)

    return obj_id


def map_main_events(node: Dict[str, Any], builder: OCELBuilder,
                    repo_id: str, obj_id: str, is_pr: bool) -> None:
    created_at = safe_timestamp(node.get("createdAt"))

    author_login = node.get("author", {}).get("login")

    author_id = ensure_user(builder, repo_id, author_login, timestamp=created_at)

    audit_attrs = {
        "source": "github_graphql_api",
        "confidence": "high"
    }
    # EVENT: OPENED
    if created_at:
        evt_open = Event(
            event_id=str(uuid.uuid4()),
            event_type=Activities.PR_OPENED if is_pr else Activities.ISSUE_OPENED,
            time=created_at,
            attributes=audit_attrs
        )
        evt_open.add_rel(obj_id, "subject")
        evt_open.add_rel(repo_id, "context")

        if author_id:
            evt_open.add_rel(author_id, "actor")

        builder.insert_event(evt_open)

    # EVENT: CLOSED
    if node.get("closedAt"):
        closed_at = node["closedAt"]
        evt_close = Event(
            event_id=str(uuid.uuid4()),
            event_type=Activities.PR_CLOSED if is_pr else Activities.ISSUE_CLOSED,
            time=closed_at,
            attributes=audit_attrs
        )
        evt_close.add_rel(obj_id, "subject")
        builder.insert_event(evt_close)

    # EVENT: MERGED (Only PRs)
    if is_pr and node.get("mergedAt"):
        merged_at = node["mergedAt"]
        evt_merge = Event(
            event_id=str(uuid.uuid4()),
            event_type=Activities.PR_MERGED,
            time=merged_at,
            attributes=audit_attrs
        )
        evt_merge.add_rel(obj_id, "subject")

        if node.get("mergedBy"):
            merger_login = node["mergedBy"].get("login")
            merger_id = ensure_user(builder, repo_id, merger_login, timestamp=merged_at)
            if merger_id:
                evt_merge.add_rel(merger_id, "actor")

        builder.insert_event(evt_merge)

def map_management_context(node: Dict[str, Any], builder: OCELBuilder, obj_id: str) -> None:
    milestone = node.get("milestone")
    if not milestone:
        return

    m_id = f"milestone_{milestone['id']}"
    m_created_at = milestone.get("createdAt") or node.get("createdAt")

    m_obj = ObjectInstance(object_id=m_id, object_type="Milestone")
    m_obj.add_snapshot(
        time=safe_timestamp(m_created_at),
        attributes={
            "title": milestone.get("title", ""),
            "due_on": safe_timestamp(milestone.get("dueOn")),
            "state": milestone.get("state", "OPEN")
        }
    )
    m_obj.add_rel(target_id=obj_id, qualifier="milestone_for")

    # Issue/PR -> Milestone
    builder.insert_object(m_obj)

