from typing import Dict, Any
from shared.ocel.builder import OCELBuilder
from shared.ocel.model.models import ObjectInstance, ObjectSnapshot
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user
from github2ocel.transform.utils.activity import Activities
from shared.logger import get_logger

logger = get_logger(__name__)


def process_milestone(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    ms_id_raw = node.get("id") or str(node.get("number", ""))
    if not ms_id_raw:
        logger.warning("[process_milestone] Missing id/number. Skipping.")
        return

    ms_id      = make_id(repo_id, "milestone", ms_id_raw)
    created_at = safe_timestamp(node.get("createdAt"))
    closed_at  = safe_timestamp(node.get("closedAt")) if node.get("closedAt") else None
    updated_at = safe_timestamp(node.get("updatedAt"))
    is_closed  = node.get("state") == "CLOSED"

    # Object
    obj = ObjectInstance(object_id=ms_id, object_type="Milestone")

    obj.add_snapshot(
        time=created_at,
        attributes={
            "number":       node.get("number"),
            "title":        node.get("title", "")[:255],
            "description":  (node.get("description") or "")[:500],
            "state":        node.get("state", "OPEN"),
            "due_on":       safe_timestamp(node.get("dueOn")) if node.get("dueOn") else None,
            "progress_pct": node.get("progressPercentage", 0.0),
            "open_issues":   (node.get("issues")       or {}).get("totalCount", 0),
            "closed_issues": (node.get("closedIssues") or {}).get("totalCount", 0),
            "open_prs":      (node.get("pullRequests") or {}).get("totalCount", 0),
            "merged_prs":    (node.get("mergedPRs")    or {}).get("totalCount", 0),
            "url":           node.get("url", ""),
        }
    )

    # Closed snapshot — explicit changed_field so OCEL 2.0 tracks what changed
    if is_closed and closed_at:
        obj.snapshots.append(ObjectSnapshot(
            time=closed_at,
            attributes={
                "state":        "CLOSED",
                "progress_pct": 100.0,
            },
            changed_field="state",
        ))

    # Relationships
    obj.add_rel(repo_id, "contained_in")

    creator_id    = None
    creator_login = (node.get("creator") or {}).get("login")
    if creator_login:
        creator_id = ensure_user(builder, repo_id, creator_login, timestamp=created_at)
        if creator_id:
            obj.add_rel(creator_id, "created_by")

    builder.insert_object(obj)

    # Build relationships explicitly — no inline None entries
    base_rels = [(ms_id, "subject"), (repo_id, "context")]
    if creator_id:
        base_rels.append((creator_id, "actor"))

    # Event 1: MilestoneCreated
    create_event(
        builder=builder,
        event_type=Activities.MILESTONE_CREATED,
        ts=created_at,
        attributes={
            "title":  node.get("title", "")[:255],
            "due_on": safe_timestamp(node.get("dueOn")) if node.get("dueOn") else None,
            "source": "graphql",
        },
        relationships=base_rels,
    )

    # Event 2: MilestoneClosed
    if is_closed and closed_at:
        create_event(
            builder=builder,
            event_type=Activities.MILESTONE_CLOSED,
            ts=closed_at,
            attributes={
                "title":  node.get("title", "")[:255],
                "source": "graphql",
            },
            relationships=base_rels,
        )

    # Event 3: MilestoneUpdated — only when updatedAt differs from both
    # createdAt and closedAt, meaning a genuine intermediate update occurred.
    if updated_at and updated_at != created_at and updated_at != closed_at:
        create_event(
            builder=builder,
            event_type=Activities.MILESTONE_UPDATED,
            ts=updated_at,
            attributes={
                "title":        node.get("title", "")[:255],
                "progress_pct": node.get("progressPercentage", 0.0),
                "source":       "graphql",
            },
            relationships=base_rels,
        )