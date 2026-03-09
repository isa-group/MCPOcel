import logging
from typing import Dict, Any

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_commit
from github2ocel.transform.utils.activity import Activities
from shared.ocel.model.models import ObjectInstance

logger = logging.getLogger(__name__)


def process_branch(branch: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
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