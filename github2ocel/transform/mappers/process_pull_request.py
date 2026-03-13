from typing import Dict, Any
from shared.ocel.builder import OCELBuilder
from shared.ocel.model.models import ObjectInstance
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user, ensure_label
from github2ocel.transform.utils.activity import Activities
from shared.logger import get_logger

logger = get_logger(__name__)


def process_pull_request(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    number = node.get("number")
    if not number:
        logger.warning("[process_pull_request] Missing number. Skipping.")
        return

    obj_id     = make_id(repo_id, "pr", number)
    created_at = safe_timestamp(node.get("createdAt"))
    merged_at  = safe_timestamp(node.get("mergedAt"))  if node.get("mergedAt")  else None
    closed_at  = safe_timestamp(node.get("closedAt"))  if node.get("closedAt")  else None

    body_text = node.get("bodyText") or ""

    # Object: PullRequest
    obj = ObjectInstance(object_id=obj_id, object_type="PullRequest")
    obj.add_snapshot(
        time=created_at,
        attributes={
            "number":             int(number),
            "title":              (node.get("title") or "")[:255],
            "state":              node.get("state", "OPEN"),
            "is_draft":           int(node.get("isDraft", False)),
            "locked":             1 if node.get("locked") else 0,
            "locked_reason":      node.get("activeLockReason") or "",
            "merged":             int(node.get("merged", False)),
            "url":                node.get("url", ""),
            "head_ref":           node.get("headRefName", ""),
            "base_ref":           node.get("baseRefName", ""),
            "additions":          node.get("additions", 0),
            "deletions":          node.get("deletions", 0),
            "changed_files":      node.get("changedFiles", 0),
            "total_changes":      node.get("additions", 0) + node.get("deletions", 0),
            "review_decision":    node.get("reviewDecision") or "",
            "commits_count":      (node.get("commits")      or {}).get("totalCount", 0),
            "comments_count":     (node.get("comments")     or {}).get("totalCount", 0),
            "participants_count": (node.get("participants")  or {}).get("totalCount", 0),
            "reactions_count":    (node.get("reactions")     or {}).get("totalCount", 0),
            "body_length":        len(body_text),
            "updated_at":         safe_timestamp(node.get("updatedAt")),
            "merged_at":          merged_at,
            "closed_at":          closed_at,
        }
    )

    # O2O: PR -> Repository
    obj.add_rel(repo_id, "contained_in")

    # O2O: PR -> Author
    author_login = (node.get("author") or {}).get("login")
    author_id = ensure_user(builder, repo_id, author_login, timestamp=created_at) if author_login else None
    if author_id:
        obj.add_rel(author_id, "created_by")

    # O2O: PR -> Assignees
    for assignee in (node.get("assignees") or {}).get("nodes", []):
        a_id = ensure_user(builder, repo_id, assignee.get("login"), timestamp=created_at)
        if a_id:
            obj.add_rel(a_id, "assigned_to")

    # O2O: PR -> Labels
    for lbl in (node.get("labels") or {}).get("nodes", []):
        lbl_id = ensure_label(builder, repo_id, lbl, timestamp=created_at)
        if lbl_id:
            obj.add_rel(lbl_id, "has_label")

    # O2O: PR -> Milestone (object already exists from Phase 0)
    milestone = node.get("milestone")
    if milestone and milestone.get("id"):
        ms_id = make_id(repo_id, "milestone", milestone["id"])
        if builder.object_exists(ms_id):
            obj.add_rel(ms_id, "belongs_to_milestone")

    # O2O: PR -> Branches
    base_branch_id = make_id(repo_id, "branch", node.get("baseRefName", ""))
    head_branch_id = make_id(repo_id, "branch", node.get("headRefName", ""))
    if builder.object_exists(base_branch_id):
        obj.add_rel(base_branch_id, "targets_branch")
    if builder.object_exists(head_branch_id):
        obj.add_rel(head_branch_id, "source_branch")

    # NOTE: PR -> Commit O2O links are NOT built here.
    # fetch_pr_commits (Phase 2) fully paginates commits per PR.
    # process_commit_graphql (Phase 4) resolves the reverse link commit -> PR.

    builder.insert_object(obj)

    # Event: PROpened
    create_event(
        builder=builder,
        event_type=Activities.PR_OPENED,
        ts=created_at,
        attributes={"is_draft": int(node.get("isDraft", False)), "source": "graphql"},
        relationships=[
            (obj_id,     "subject"),
            (repo_id,    "context"),
            (author_id,  "actor") if author_id else None,
        ]
    )

    # Event: PRMerged
    if node.get("merged") and merged_at:
        merger_login = (node.get("mergedBy") or {}).get("login")
        merger_id = ensure_user(builder, repo_id, merger_login, timestamp=merged_at) if merger_login else None

        create_event(
            builder=builder,
            event_type=Activities.PR_MERGED,
            ts=merged_at,
            attributes={
                "merge_ref": node.get("headRefName", ""),
                "additions": node.get("additions", 0),
                "deletions": node.get("deletions", 0),
            },
            relationships=[
                (obj_id,          "subject"),
                (repo_id,         "context"),
                (merger_id,       "actor")       if merger_id else None,
                (base_branch_id,  "merged_into") if builder.object_exists(base_branch_id) else None,
            ]
        )

    # Event: PRClosed (without merge)
    elif node.get("state") == "CLOSED" and closed_at:
        create_event(
            builder=builder,
            event_type=Activities.PR_CLOSED,
            ts=closed_at,
            attributes={"source": "graphql"},
            relationships=[
                (obj_id,    "subject"),
                (repo_id,   "context"),
                (author_id, "actor") if author_id else None,
            ]
        )

    # Event: PRCIState — lightweight CI summary from statusCheckRollup.state
    # Detailed CI is modelled via WorkflowRun/Job objects in Phase 6.
    ci_state = (node.get("statusCheckRollup") or {}).get("state")
    if ci_state:
        create_event(
            builder=builder,
            event_type=Activities.PR_CI_STATE,
            ts=safe_timestamp(node.get("updatedAt")),
            attributes={"ci_state": ci_state},
            relationships=[
                (obj_id,  "subject"),
                (repo_id, "context"),
            ]
        )

    # NOTE: PRCommentCreated events are NOT mapped here.
    # All comments are fetched and mapped in Phase 2 (fetch_pr_comments)
    # to avoid duplicate events and ensure full pagination coverage.


def _map_comment(
    comment: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
    pr_id: str,
) -> None:
    if not comment.get("id"):
        return

    ts = safe_timestamp(comment.get("createdAt"))
    author_login = (comment.get("author") or {}).get("login")
    author_id = ensure_user(builder, repo_id, author_login, timestamp=ts) if author_login else None

    create_event(
        builder=builder,
        event_type=Activities.PR_COMMENT_CREATED,
        ts=ts,
        attributes={
            "comment_id":  comment["id"],
            "body_length": len(comment.get("bodyText") or ""),
            "is_edited":   1 if comment.get("lastEditedAt") else 0,
        },
        relationships=[
            (pr_id,     "target"),
            (repo_id,   "context"),
            (author_id, "actor") if author_id else None,
        ]
    )


# Phase 2: standalone mappers (called from fetch_pr_commits / fetch_pr_comments)

def process_pr_commit_link(link: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Create PullRequest -> Commit O2O link.

    Called from Phase 2. At this point Commit objects don't exist yet (Phase 4),
    so most links won't resolve here. The reverse link (commit -> PR) is handled
    by process_commit_graphql in Phase 4 via associatedPullRequests.
    We still attempt the forward link in case a commit was already inserted.
    """
    pr_number = link.get("__pr_number")
    oid       = link.get("oid")
    if not pr_number or not oid:
        return

    pr_id     = make_id(repo_id, "pr", pr_number)
    commit_id = make_id(repo_id, "commit", oid)

    if not builder.object_exists(pr_id):
        return

    if builder.object_exists(commit_id):
        from shared.ocel.model.models import ObjectInstance as _OI
        proxy = _OI(object_id=pr_id, object_type="PullRequest")
        proxy.add_rel(commit_id, "contains_commit")
        builder.insert_object(proxy)


def process_pr_comment(comment: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Map a single PR comment to a PRCommentCreated event.
    Called from Phase 2 with fully paginated comment nodes.

    The comment dict must have "__pr_number" injected by fetch_pr_comments().
    """
    pr_number = comment.get("__pr_number")
    if not pr_number:
        return

    pr_id = make_id(repo_id, "pr", pr_number)
    if not builder.object_exists(pr_id):
        return

    _map_comment(comment, builder, repo_id, pr_id)