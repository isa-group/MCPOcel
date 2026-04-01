from typing import Dict, Any

from shared.ocel.builder import OCELBuilder
from shared.ocel.model.models import ObjectInstance
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_commit, ensure_user
from github2ocel.transform.utils.activity import Activities
from shared.logger import get_logger

logger = get_logger(__name__)


def process_branch(branch: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Register a GitHub branch (GraphQL Ref) as an OCEL 2.0 object.

    Source: BRANCHES_QUERY (refs/heads/), called from the Init phase.

    Snapshot timestamp: HEAD commit's committedDate — the last recorded
    activity on the branch. Falls back to extraction time when the branch
    has no reachable commit (e.g. empty or orphaned ref).

    GitHub does not expose a branch createdAt — no BranchCreated event is
    generated here. BranchCreated events come from HeadRefCreatedEvent in
    the PR timeline (Phase 3) for branches associated with a PR.
    """
    branch_name = branch.get("name")
    if not branch_name:
        return

    try:
        branch_id = make_id(repo_id, "branch", branch_name)
    except ValueError:
        logger.warning(f"[process_branch] Invalid branch name '{branch_name}' — skipping.")
        return

    # HEAD commit metadata
    target = branch.get("target") or {}
    sha = target.get("oid") or ""
    committed = target.get("committedDate")
    author_login = ((target.get("author") or {}).get("user") or {}).get("login") or ""

    # Snapshot timestamp: committedDate when available, extraction time otherwise
    ts = safe_timestamp(committed, use_now=True)

    # Branch protection rule — empty dict when unprotected
    bpr = branch.get("branchProtectionRule") or {}
    is_protected = bool(bpr)
    req_checks = bpr.get("requiredStatusCheckContexts") or []

    # Associated PR count
    pr_count = (branch.get("associatedPullRequests") or {}).get("totalCount", 0)

    # Object: Branch
    branch_obj = ObjectInstance(object_id=branch_id, object_type="Branch")
    branch_obj.add_snapshot(
        time=safe_timestamp(None), # unix epoch OCEL2.0 standard
        attributes={
            "name":                             branch_name,
            "github_node_id":                   branch.get("id", ""),
            "head_sha":                         sha,
            "head_author_login":                author_login,
            "associated_pr_count":              pr_count,
            "protected":                        int(is_protected),
            "requires_approving_reviews":       int(bpr.get("requiresApprovingReviews", False)),
            "required_approving_review_count":  bpr.get("requiredApprovingReviewCount", 0) or 0,
            "requires_status_checks":           int(bpr.get("requiresStatusChecks", False)),
            "required_status_checks":           ", ".join(req_checks),
            "requires_linear_history":          int(bpr.get("requiresLinearHistory", False)),
            "allows_force_pushes":              int(bpr.get("allowsForcePushes", False)),
            "allows_deletions":                 int(bpr.get("allowsDeletions", False)),
            "is_admin_enforced":                int(bpr.get("isAdminEnforced", False)),
            "requires_conversation_resolution": int(bpr.get("requiresConversationResolution", False)),
            "requires_code_owner_reviews":      int(bpr.get("requiresCodeOwnerReviews", False)),
        }
    )

    # O2O: Branch -> Repository
    branch_obj.add_rel(repo_id, "contained_in")

    # O2O: Branch -> HEAD Commit (stub — Phase 4 enriches with full commit data)
    commit_id = None
    if sha:
        commit_id = ensure_commit(builder, repo_id, sha, timestamp=ts)
        if commit_id:
            branch_obj.add_rel(commit_id, "current_head")

    # O2O: Branch -> HEAD commit author
    author_id = None
    if author_login:
        author_id = ensure_user(builder, repo_id, author_login, timestamp=ts)
        if author_id:
            branch_obj.add_rel(author_id, "last_author")

    builder.insert_object(branch_obj)

    # Event: BranchSnapshot — observation event, not a lifecycle transition
    rels = [
        (branch_id, "observed_branch"),
        (repo_id,   "context"),
    ]
    if commit_id:
        rels.append((commit_id, "head_commit"))
    if author_id:
        rels.append((author_id, "actor"))

    create_event(
        builder=builder,
        event_type=Activities.BRANCH_OBSERVED,
        ts=ts,
        attributes={
            "source":    "graphql",
            "protected": int(is_protected),
        },
        relationships=rels,
    )