from typing import Dict, Any
from shared.ocel.builder import OCELBuilder
from shared.ocel.model.models import ObjectInstance
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user, ensure_label, ensure_commit
from github2ocel.transform.utils.reactions import parse_reaction_groups
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.mappers.process_comment import map_pr_comment
from shared.logger import get_logger

logger = get_logger(__name__)


def process_pull_request(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    number = node.get("number")
    if not number:
        logger.warning("[process_pull_request] Missing number. Skipping.")
        return

    obj_id = make_id(repo_id, "pr", number)
    created_at = safe_timestamp(node.get("createdAt"))
    merged_at = safe_timestamp(node.get("mergedAt"))  if node.get("mergedAt")  else None
    closed_at = safe_timestamp(node.get("closedAt"))  if node.get("closedAt")  else None

    body_text = node.get("bodyText") or ""

    reactions = parse_reaction_groups(node.get("reactionGroups", []))

    # Extract Auto-Merge
    auto_merge = node.get("autoMergeRequest") or {}
    am_enabled = 1 if auto_merge else 0
    am_method = auto_merge.get("mergeMethod") or ""
    am_author = (auto_merge.get("enabledBy") or {}).get("login") or ""

    head_repo = (node.get("headRepository") or {}).get("nameWithOwner", "")
    base_repo = (node.get("baseRepository") or {}).get("nameWithOwner", "")

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
            "author_association": node.get("authorAssociation", ""),
            "github_node_id":     node.get("id", ""),
            "head_sha":           node.get("headRefOid", ""),
            "head_repo":          head_repo,
            "is_fork_pr":         1 if   head_repo and head_repo != base_repo else 0,
            "merged_by":          (node.get("mergedBy") or {}).get("login", ""),
            "am_enabled":         am_enabled,
            "am_method":          am_method,
            "am_enabled_by":      am_author,
            "commits_count":      (node.get("commits")      or {}).get("totalCount", 0),
            "comments_count":     (node.get("comments")     or {}).get("totalCount", 0),
            "participants_count": (node.get("participants")  or {}).get("totalCount", 0),
            "reactions_count":    (node.get("reactions")     or {}).get("totalCount", 0),
            "body_length":        len(body_text),
            "updated_at":         safe_timestamp(node.get("updatedAt")),
            "merged_at":          merged_at,
            "closed_at":          closed_at,
            **reactions,
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

    # NOTE: PRMerged and PRClosed events are NOT generated here.
    # Phase 3 timeline (MergedEvent, ClosedEvent) is the single source of truth
    # for lifecycle events — it carries actor, closer_type, and exact timestamp.

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


def process_pr_comment(comment: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Map a single PR comment to a Comment object + CommentCreated event.
    Called from Phase 2 with fully paginated comment nodes.
    The comment dict must have "__pr_number" injected by fetch_pr_comments().
    """
    pr_number = comment.get("__pr_number")
    if not pr_number:
        return

    pr_id = make_id(repo_id, "pr", pr_number)
    if not builder.object_exists(pr_id):
        return

    map_pr_comment(comment, builder, repo_id, pr_id)

def process_pr_commit_link(pr_number: int, oid: str, builder: OCELBuilder, repo_id: str) -> None:
    """
    Create PullRequest ──contains_commit──► Commit O2O link.

    Called from Phase 4 (process_commit_graphql) after the Commit object exists.
    If the Commit is a feature-branch commit that was never inserted as a stub,
    ensure_commit creates one so the O2O is never silently dropped.
    """
    pr_id = make_id(repo_id, "pr", pr_number)
    if not builder.object_exists(pr_id):
        return

    commit_id = ensure_commit(builder, repo_id, oid)
    if not commit_id:
        return

    proxy = ObjectInstance(object_id=pr_id, object_type="PullRequest")
    proxy.add_rel(commit_id, "contains_commit")
    builder.insert_object(proxy)