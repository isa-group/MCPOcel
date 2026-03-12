import logging
from typing import Dict, Any

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_commit, ensure_user
from github2ocel.transform.utils.activity import Activities
from shared.ocel.model.models import ObjectInstance

logger = logging.getLogger(__name__)


def process_branch(branch: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Processes a GitHub branch node (GraphQL Ref) and registers it in OCEL 2.0.

    Uses GraphQL refs/heads/ which provides:
    - HEAD commit SHA and real committedDate
    - HEAD commit author login
    - branchProtectionRule with full protection configuration

    Note: The Ref object has no createdAt in the GitHub API.
    The HEAD commit's committedDate is used as the snapshot timestamp,
    which represents the last known activity on the branch.
    """
    branch_name = branch.get("name")
    if not branch_name:
        return

    try:
        branch_id = make_id(repo_id, "branch", branch_name)
    except ValueError:
        return

    # HEAD commit data from GraphQL target
    target     = branch.get("target") or {}
    sha        = target.get("oid")
    committed  = target.get("committedDate")
    author     = (target.get("author") or {})
    author_login = (author.get("user") or {}).get("login")

    # Use HEAD commit date as snapshot timestamp — more meaningful than now()
    ts = safe_timestamp(committed, use_now=True)

    # Branch protection rule
    bpr = branch.get("branchProtectionRule") or {}
    is_protected = bpr is not None and bool(bpr)
    required_checks = bpr.get("requiredStatusCheckContexts") or []

    branch_obj = ObjectInstance(object_id=branch_id, object_type="Branch")
    branch_obj.add_snapshot(
        time=ts,
        attributes={
            "name":                          branch_name,
            "head_sha":                      sha or "",
            "head_committed_date":           safe_timestamp(committed) if committed else "",
            "head_author_login":             author_login or "",
            "protected":                     int(is_protected),
            "requires_approving_reviews":    int(bpr.get("requiresApprovingReviews", False)),
            "required_approving_review_count": bpr.get("requiredApprovingReviewCount", 0) or 0,
            "requires_status_checks":        int(bpr.get("requiresStatusChecks", False)),
            "required_status_checks":        ", ".join(required_checks) if required_checks else "",
            "requires_linear_history":       int(bpr.get("requiresLinearHistory", False)),
            "allows_force_pushes":           int(bpr.get("allowsForcePushes", False)),
            "allows_deletions":              int(bpr.get("allowsDeletions", False)),
            "is_admin_enforced":             int(bpr.get("isAdminEnforced", False)),
            "requires_conversation_resolution": int(bpr.get("requiresConversationResolution", False)),
            "requires_code_owner_reviews":   int(bpr.get("requiresCodeOwnerReviews", False)),
        }
    )

    # O2O: Branch -> Repository
    branch_obj.add_rel(target_id=repo_id, qualifier="branch_of_repo")

    # O2O: Branch -> Commit HEAD (stub — Phase 4 enriches with full data)
    commit_id = None
    if sha:
        commit_id = ensure_commit(builder, repo_id, sha, timestamp=ts)
        if commit_id:
            branch_obj.add_rel(target_id=commit_id, qualifier="current_head")

    # O2O: Branch -> Author of HEAD commit
    author_id = None
    if author_login:
        author_id = ensure_user(builder, repo_id, author_login, timestamp=ts)
        if author_id:
            branch_obj.add_rel(target_id=author_id, qualifier="last_author")

    builder.insert_object(branch_obj)

    # Event: BranchSnapshot (observation — no creation date available)
    rels = [(branch_id, "observed_branch"), (repo_id, "context")]
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

def process_branch_rest(branch: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Processes a GitHub branch and registers it in OCEL 2.0.

    Note: The REST branches API does not expose a creation date.
    The timestamp used is the extraction time (observation snapshot),
    not the actual branch creation time.
    """
    branch_name = branch.get("name")
    if not branch_name:
        return

    try:
        branch_id = make_id(repo_id, "branch", branch_name)
    except ValueError:
        return

    sha = branch.get("commit", {}).get("sha")

    # REST branches have no creation date — use extraction time as observation timestamp
    ts_observation = safe_timestamp(None, use_now=True)

    # Protection details (available when branch has branch protection rules)
    protection = branch.get("protection") or {}
    required_checks = protection.get("required_status_checks") or {}

    branch_obj = ObjectInstance(object_id=branch_id, object_type="Branch")
    branch_obj.add_snapshot(
        time=ts_observation,
        attributes={
            "name": branch_name,
            "protected": int(branch.get("protected", False)),
            "head_sha": sha,
            "protection_enforcement": required_checks.get("enforcement_level", ""),
            "required_checks": ", ".join(required_checks.get("contexts", [])) or "",
        }
    )

    # O2O: Branch -> Repository
    branch_obj.add_rel(target_id=repo_id, qualifier="branch_of_repo")

    # O2O: Branch -> Commit HEAD (placeholder — Phase 4 fills in full commit data)
    commit_id = None
    if sha:
        commit_id = ensure_commit(builder, repo_id, sha, timestamp=ts_observation)
        if commit_id:
            branch_obj.add_rel(target_id=commit_id, qualifier="current_head")

    builder.insert_object(branch_obj)

    create_event(
        builder=builder,
        event_type=Activities.BRANCH_OBSERVED,
        ts=ts_observation,
        attributes={
            "source": "rest_api_snapshot",
            "protected": int(branch.get("protected", False)),
        },
        relationships=[
            (branch_id, "observed_branch"),
            (repo_id, "context"),
            (commit_id, "head_commit") if commit_id else None,
        ]
    )