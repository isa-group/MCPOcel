from typing import Dict, Any, Optional
from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user, ensure_team, ensure_label, ensure_branch
from github2ocel.transform.utils.activity import Activities
from shared.ocel.model.models import ObjectInstance
from shared.logger import get_logger

logger = get_logger(__name__)


def process_timeline_event(
    item: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
) -> None:
    typename    = item.get("__typename")
    parent_type = item.get("__parent_type", "PullRequest")
    is_pr       = parent_type == "PullRequest"

    # Resolve parent object ID
    if is_pr:
        pr_num = item.get("__pr_number")
        if not pr_num:
            return
        parent_id = make_id(repo_id, "pr", pr_num)
    else:
        issue_num = item.get("__issue_number")
        if not issue_num:
            return
        parent_id = make_id(repo_id, "issue", issue_num)

    if not builder.object_exists(parent_id):
        logger.debug(f"[timeline] Parent {parent_id} not in builder yet. Skipping {typename}.")
        return

    handler = _HANDLERS.get(typename)
    if not handler:
        return  # unknown/unsupported type — silent skip

    try:
        handler(item, builder, repo_id, parent_id, is_pr)
    except Exception as e:
        logger.warning(f"[timeline] Failed to process {typename} on {parent_id}: {e}")


# Handlers
def _handle_assigned(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    actor_id    = _resolve_user(builder, repo_id, item.get("actor"), ts)
    assignee_id = _resolve_user(builder, repo_id, item.get("assignee"), ts)

    activity = Activities.PR_ASSIGNED if is_pr else Activities.ISSUE_ASSIGNED

    create_event(
        builder=builder, event_type=activity, ts=ts,
        attributes={"source": "timeline"},
        relationships=[
            (parent_id, "target"),
            (actor_id,  "actor")    if actor_id    else None,
            (assignee_id, "assignee") if assignee_id else None,
        ]
    )
    # Update O2O object relationship
    if assignee_id:
        _add_o2o(builder, parent_id, "PullRequest" if is_pr else "Issue",
                 assignee_id, "assigned_to")


def _handle_unassigned(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    actor_id    = _resolve_user(builder, repo_id, item.get("actor"), ts)
    assignee_id = _resolve_user(builder, repo_id, item.get("assignee"), ts)

    activity = Activities.PR_UNASSIGNED if is_pr else Activities.ISSUE_UNASSIGNED

    create_event(
        builder=builder, event_type=activity, ts=ts,
        attributes={"source": "timeline"},
        relationships=[
            (parent_id,   "target"),
            (actor_id,    "actor")      if actor_id    else None,
            (assignee_id, "unassigned") if assignee_id else None,
        ]
    )


def _handle_review_requested(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    actor_id = _resolve_user(builder, repo_id, item.get("actor"), ts)

    reviewer_node = item.get("requestedReviewer") or {}
    reviewer_type = reviewer_node.get("__typename")

    if reviewer_type == "User":
        reviewer_id = _resolve_user(builder, repo_id, reviewer_node, ts)
    elif reviewer_type == "Team":
        reviewer_id = ensure_team(builder, repo_id, reviewer_node)
    else:
        reviewer_id = None

    create_event(
        builder=builder, event_type=Activities.PR_REVIEW_REQUESTED, ts=ts,
        attributes={"reviewer_type": reviewer_type or "", "source": "timeline"},
        relationships=[
            (parent_id,   "target"),
            (actor_id,    "actor")    if actor_id    else None,
            (reviewer_id, "reviewer") if reviewer_id else None,
        ]
    )


def _handle_review_request_removed(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    actor_id = _resolve_user(builder, repo_id, item.get("actor"), ts)

    create_event(
        builder=builder, event_type=Activities.PR_REVIEW_REQUEST_REMOVED, ts=ts,
        attributes={"source": "timeline"},
        relationships=[
            (parent_id, "target"),
            (actor_id,  "actor") if actor_id else None,
        ]
    )


def _handle_ready_for_review(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    actor_id = _resolve_user(builder, repo_id, item.get("actor"), ts)

    create_event(
        builder=builder, event_type=Activities.PR_FOR_REVIEW, ts=ts,
        attributes={"source": "timeline"},
        relationships=[
            (parent_id, "subject"),
            (actor_id,  "actor") if actor_id else None,
        ]
    )


def _handle_convert_to_draft(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    actor_id = _resolve_user(builder, repo_id, item.get("actor"), ts)

    create_event(
        builder=builder, event_type=Activities.PR_CONVERT_DRAFT, ts=ts,
        attributes={"source": "timeline"},
        relationships=[
            (parent_id, "subject"),
            (actor_id,  "actor") if actor_id else None,
        ]
    )


def _handle_labeled(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    actor_id = _resolve_user(builder, repo_id, item.get("actor"), ts)
    lbl = item.get("label") or {}
    lbl_id = ensure_label(builder, repo_id, lbl, timestamp=ts) if lbl.get("id") else None

    create_event(
        builder=builder, event_type=Activities.LABEL_ADDED, ts=ts,
        attributes={"label_name": lbl.get("name", ""), "source": "timeline"},
        relationships=[
            (parent_id, "target"),
            (lbl_id,    "label_applied") if lbl_id   else None,
            (actor_id,  "actor")         if actor_id else None,
        ]
    )
    if lbl_id:
        _add_o2o(builder, parent_id, "PullRequest" if is_pr else "Issue",
                 lbl_id, "has_label")


def _handle_unlabeled(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    actor_id = _resolve_user(builder, repo_id, item.get("actor"), ts)
    lbl = item.get("label") or {}

    create_event(
        builder=builder, event_type=Activities.LABEL_REMOVED, ts=ts,
        attributes={"label_name": lbl.get("name", ""), "source": "timeline"},
        relationships=[
            (parent_id, "target"),
            (actor_id,  "actor") if actor_id else None,
        ]
    )


def _handle_milestoned(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    actor_id = _resolve_user(builder, repo_id, item.get("actor"), ts)

    create_event(
        builder=builder, event_type=Activities.MILESTONE_ASSIGNED, ts=ts,
        attributes={"milestone_title": item.get("milestoneTitle", ""), "source": "timeline"},
        relationships=[
            (parent_id, "target"),
            (actor_id,  "actor") if actor_id else None,
        ]
    )


def _handle_demilestoned(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    actor_id = _resolve_user(builder, repo_id, item.get("actor"), ts)

    create_event(
        builder=builder, event_type=Activities.MILESTONE_REMOVED, ts=ts,
        attributes={"milestone_title": item.get("milestoneTitle", ""), "source": "timeline"},
        relationships=[
            (parent_id, "target"),
            (actor_id,  "actor") if actor_id else None,
        ]
    )


def _handle_closed(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    actor_id = _resolve_user(builder, repo_id, item.get("actor"), ts)
    activity = Activities.PR_CLOSED if is_pr else Activities.ISSUE_CLOSED

    # Closer can be a PR or Commit
    closer = item.get("closer") or {}
    closer_type = closer.get("__typename", "")
    closer_ref = closer.get("number") or closer.get("oid", "")

    # O2O: Issue → PR that closed it (only when an Issue is closed by a PR)
    if not is_pr and closer_type == "PullRequest" and closer.get("number"):
        closing_pr_id = make_id(repo_id, "pr", closer["number"])
        if builder.object_exists(closing_pr_id):
            _add_o2o(builder, parent_id, "Issue", closing_pr_id, "closed_by")

    create_event(
        builder=builder, event_type=activity, ts=ts,
        attributes={
            "closer_type": closer_type,
            "closer_ref": str(closer_ref),
            "source": "timeline",
        },
        relationships=[
            (parent_id, "subject"),
            (actor_id,  "actor") if actor_id else None,
        ]
    )


def _handle_reopened(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    actor_id = _resolve_user(builder, repo_id, item.get("actor"), ts)
    activity = Activities.PR_REOPENED if is_pr else Activities.ISSUE_REOPENED

    create_event(
        builder=builder, event_type=activity, ts=ts,
        attributes={"source": "timeline"},
        relationships=[
            (parent_id, "subject"),
            (actor_id,  "actor") if actor_id else None,
        ]
    )


def _handle_merged(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    actor_id = _resolve_user(builder, repo_id, item.get("actor"), ts)
    merge_commit_oid = (item.get("commit") or {}).get("oid")
    
    # IPORTANT: Ensure the merge commit (Stub) in case it doesn't exist yet (Phase 4 pending)
    merge_commit_id = None
    if merge_commit_oid:
        merge_commit_id = make_id(repo_id, "commit", merge_commit_oid)
        if not builder.object_exists(merge_commit_id):
            stub_commit = ObjectInstance(object_id=merge_commit_id, object_type="Commit")
            stub_commit.add_snapshot(time=ts, attributes={"sha": merge_commit_oid})
            builder.insert_object(stub_commit)

    create_event(
        builder=builder, event_type=Activities.PR_MERGED, ts=ts,
        attributes={"merge_ref": item.get("mergeRefName", ""), "source": "timeline"},
        relationships=[
            (parent_id,       "subject"),
            (actor_id,        "actor")        if actor_id        else None,
            (merge_commit_id, "merge_commit") if merge_commit_id else None,
        ]
    )

    head_ref_name = item.get("__pr_head_ref", "")
    if head_ref_name:

        branch_id = ensure_branch(builder, repo_id, head_ref_name, timestamp=ts)
        
        merge_ref_name  = item.get("mergeRefName", "")
        target_branch_id = ensure_branch(builder, repo_id, merge_ref_name, timestamp=ts)

        create_event(
            builder=builder, event_type=Activities.BRANCH_MERGED, ts=ts,
            attributes={
                "branch_name":  head_ref_name,
                "merged_into":  merge_ref_name,
                "source":       "timeline",
            },
            relationships=[
                (parent_id,        "context"),
                (actor_id,         "actor")         if actor_id         else None,
                (branch_id,        "merged_branch") if branch_id        else None,
                (target_branch_id, "merged_into")   if target_branch_id else None,
                (merge_commit_id,  "merge_commit")  if merge_commit_id  else None,
            ]
        )

def _handle_force_pushed(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    actor_id = _resolve_user(builder, repo_id, item.get("actor"), ts)
    before_oid = (item.get("beforeCommit") or {}).get("oid", "")
    after_oid  = (item.get("afterCommit")  or {}).get("oid", "")

    create_event(
        builder=builder, event_type=Activities.PR_FORCE_PUSHED, ts=ts,
        attributes={"before_sha": before_oid[:12], "after_sha": after_oid[:12], "source": "timeline"},
        relationships=[
            (parent_id, "target"),
            (actor_id,  "actor") if actor_id else None,
        ]
    )


def _handle_deployed(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    dep = item.get("deployment") or {}
    dep_db_id = dep.get("databaseId")

    dep_rel = None
    if dep_db_id:
        # Deployments are extracted in Phase 6, so we’ll create a stub here (Phase 3)
        dep_id = make_id(repo_id, "deployment", dep_db_id)
        if not builder.object_exists(dep_id):
            stub_dep = ObjectInstance(object_id=dep_id, object_type="Deployment")
            stub_dep.add_snapshot(
                time=safe_timestamp(None), # unix epoch OCEL2.0 standard
                attributes={"environment": dep.get("environment", "unknown")}
            )
            builder.insert_object(stub_dep)

        dep_rel = (dep_id, "deployment")

    create_event(
        builder=builder, event_type=Activities.DEPLOYMENT_CREATED, ts=ts,
        attributes={
            "environment": dep.get("environment", ""),
            "state": dep.get("state", ""),
            "source": "timeline",
        },
        relationships=[
            (parent_id, "context"),
            dep_rel,
        ]
    )

def _handle_cross_referenced(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    source = item.get("source") or {}
    source_type = source.get("__typename", "")
    source_num  = source.get("number")

    source_id = None
    if source_num:
        obj_type_str = "PullRequest" if source_type == "PullRequest" else "Issue"
        potential_id = make_id(repo_id, obj_type_str.lower() if source_type == "PullRequest" else "issue", source_num)

        if builder.object_exists(potential_id):
            source_id = potential_id
            _add_o2o(builder, parent_id, "PullRequest" if is_pr else "Issue", source_id, "references")

    create_event(
        builder=builder, event_type=Activities.CROSS_REFERENCED, ts=ts,
        attributes={"source_type": source_type, "source": "timeline"},
        relationships=[
            (parent_id, "target"),
            (source_id, "referenced_by") if source_id else None,
        ]
    )

def _handle_head_ref_deleted(item, builder, repo_id, parent_id, is_pr):
    ts           = safe_timestamp(item["createdAt"])
    actor_id     = _resolve_user(builder, repo_id, item.get("actor"), ts)
    head_ref_name = item.get("headRefName", "")

    branch_id = ensure_branch(builder, repo_id, head_ref_name, timestamp=ts)

    if branch_id:
        proxy = ObjectInstance(object_id=branch_id, object_type="Branch")
        proxy.add_snapshot(time=ts, attributes={"deleted_at": ts})
        builder.insert_object(proxy)

    create_event(
        builder=builder, event_type=Activities.BRANCH_DELETED, ts=ts,
        attributes={"branch_name": head_ref_name, "source": "timeline"},
        relationships=[
            (parent_id, "subject"),
            (actor_id,  "actor")          if actor_id  else None,
            (branch_id, "deleted_branch") if branch_id else None,
        ]
    )


def _handle_connected(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])
    subject = item.get("subject") or {}
    subject_type = subject.get("__typename", "")
    subject_num  = subject.get("number")

    linked_id = None
    if subject_num:
        obj_type_str = "PullRequest" if subject_type == "PullRequest" else "Issue"
        potential_id = make_id(repo_id, obj_type_str.lower() if subject_type == "PullRequest" else "issue", subject_num)

        if builder.object_exists(potential_id):
            linked_id = potential_id
            _add_o2o(builder, parent_id, "PullRequest" if is_pr else "Issue", linked_id, "linked_issue")

    create_event(
        builder=builder, event_type=Activities.ISSUE_LINKED, ts=ts,
        attributes={"linked_type": subject_type, "source": "timeline"},
        relationships=[
            (parent_id, "subject"),
            (linked_id, "linked_to") if linked_id else None,
        ]
    )


def _handle_disconnected(item, builder, repo_id, parent_id, is_pr):
    ts = safe_timestamp(item["createdAt"])

    create_event(
        builder=builder, event_type=Activities.ISSUE_UNLINKED, ts=ts,
        attributes={"source": "timeline"},
        relationships=[(parent_id, "subject")]
    )


def _handle_head_ref_deleted(item, builder, repo_id, parent_id, is_pr):
    """
    HeadRefDeletedEvent — fires when the head branch of a PR is deleted.
    headRefName is preserved as a string even after the ref is gone,
    so we can always log which branch was deleted.
    """
    ts           = safe_timestamp(item["createdAt"])
    actor_id     = _resolve_user(builder, repo_id, item.get("actor"), ts)
    head_ref_name = item.get("headRefName", "")

    # O2O: resolve the Branch object if it still exists in the builder
    branch_id = make_id(repo_id, "branch", head_ref_name) if head_ref_name else None
    branch_exists = branch_id and builder.object_exists(branch_id)

    # Enrich Branch object with a deleted_at snapshot if it exists
    if branch_exists:
        proxy = ObjectInstance(object_id=branch_id, object_type="Branch")
        proxy.add_snapshot(time=ts, attributes={"deleted_at": ts})
        builder.insert_object(proxy)

    create_event(
        builder=builder, event_type=Activities.BRANCH_DELETED, ts=ts,
        attributes={
            "branch_name": head_ref_name,
            "source": "timeline",
        },
        relationships=[
            (parent_id, "subject"),
            (actor_id,  "actor")          if actor_id    else None,
            (branch_id, "deleted_branch") if branch_exists else None,
        ]
    )


def _handle_head_ref_restored(item, builder, repo_id, parent_id, is_pr):
    """
    HeadRefRestoredEvent — fires when a deleted head branch is restored
    (GitHub allows restoring the branch of a merged/closed PR).
    """
    ts       = safe_timestamp(item["createdAt"])
    actor_id = _resolve_user(builder, repo_id, item.get("actor"), ts)

    # GitHub doesn't expose headRefName on this event.
    # parent_id (the PR) carries the context.
    create_event(
        builder=builder, event_type=Activities.BRANCH_RESTORED, ts=ts,
        attributes={"source": "timeline"},
        relationships=[
            (parent_id, "subject"),
            (actor_id,  "actor") if actor_id else None,
        ]
    )

# Dispatch table
_HANDLERS = {
    "AssignedEvent":              _handle_assigned,
    "UnassignedEvent":            _handle_unassigned,
    "ReviewRequestedEvent":       _handle_review_requested,
    "ReviewRequestRemovedEvent":  _handle_review_request_removed,
    "ReadyForReviewEvent":        _handle_ready_for_review,
    "ConvertToDraftEvent":        _handle_convert_to_draft,
    "LabeledEvent":               _handle_labeled,
    "UnlabeledEvent":             _handle_unlabeled,
    "MilestonedEvent":            _handle_milestoned,
    "DemilestonedEvent":          _handle_demilestoned,
    "ClosedEvent":                _handle_closed,
    "ReopenedEvent":              _handle_reopened,
    "MergedEvent":                _handle_merged,
    "HeadRefForcePushedEvent":    _handle_force_pushed,
    "HeadRefDeletedEvent":        _handle_head_ref_deleted,
    "HeadRefRestoredEvent":       _handle_head_ref_restored,
    "DeployedEvent":              _handle_deployed,
    "CrossReferencedEvent":       _handle_cross_referenced,
    "ConnectedEvent":             _handle_connected,
    "DisconnectedEvent":          _handle_disconnected,
}


# Helpers
def _resolve_user(
    builder: OCELBuilder,
    repo_id: str,
    actor_node: Optional[Dict],
    ts: str,
) -> Optional[str]:
    if not actor_node:
        return None
    login = actor_node.get("login")
    return ensure_user(builder, repo_id, login, timestamp=ts) if login else None


def _add_o2o(
    builder: OCELBuilder,
    source_id: str,
    source_type: str,
    target_id: str,
    qualifier: str,
) -> None:
    """Add an O2O relationship using a proxy ObjectInstance (idempotent)."""
    proxy = ObjectInstance(object_id=source_id, object_type=source_type)
    proxy.add_rel(target_id, qualifier)
    builder.insert_object(proxy)