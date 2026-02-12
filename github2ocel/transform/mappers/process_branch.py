import logging
from typing import Dict, Any
import uuid

from github2ocel.transform.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, safe_timestamp
from github2ocel.transform.utils.ensure import ensure_commit
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.model.models import Event, ObjectInstance

logger = logging.getLogger(__name__)

def process_branch(branch: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Processes a GitHub branch and registers it in OCEL 2.0.
    """
    branch_name = branch.get("name")
    if not branch_name:
        return

    try:
        branch_id = make_id(repo_id, "branch", branch_name)
    except ValueError:
        return


    commit_node = branch.get("commit", {})
    sha = commit_node.get("sha")

    # Note: In the branches API, “commit” usually provides a URL but not a direct date.
    # For security -> timestamp "observation" if there is no actual date.
    ts_observation = safe_timestamp(None, use_now=True)

    branch_obj = ObjectInstance(object_id=branch_id, object_type="Branch")

    branch_obj.add_snapshot(
        time=ts_observation,
        attributes={
            "name": branch_name,
            "protected": int(branch.get("protected", False)),
            "head_sha": sha
        }
    )

    # O2O (Objet-Objet)
    branch_obj.add_rel(target_id=repo_id, qualifier="branch_of_repo")

    # Branch -> Commit (HEAD)
    if sha:
        commit_id = ensure_commit(builder, repo_id, sha, timestamp=ts_observation)
        if commit_id:
            branch_obj.add_rel(target_id=commit_id, qualifier="current_head")

    # Snapshot
    builder.insert_object(branch_obj)

    evt = Event(
        event_id=str(uuid.uuid4()),
        event_type=Activities.BRANCH_OBSERVED,
        time=ts_observation,
        attributes={
            "source": "rest_api_snapshot",
            "protected": int(branch.get("protected", False))
        }
    )

    evt.add_rel(branch_id, "observed_branch")
    evt.add_rel(repo_id, "context")

    builder.insert_event(evt)