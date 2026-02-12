import logging
import uuid
from typing import Dict, Any

from github2ocel.transform.builder import OCELBuilder
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.utils.helper import safe_timestamp
from github2ocel.transform.utils.ensure import ensure_user, ensure_deployment, ensure_commit
from github2ocel.transform.model.models import Event, ObjectInstance
logger = logging.getLogger(__name__)


def process_deployment(deployment: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Process a deployment from REST API with OCEL 2.0 compliance.
    """
    if not deployment.get("id"):
        return

    # 1. Ensure Object (Deployment)
    # Note: ensure_deployment calculates its own timestamp internally from the dict
    dep_id = ensure_deployment(builder, repo_id, deployment)
    if not dep_id:
        return

    # Extract timestamp for events/relationships
    ts_created = safe_timestamp(deployment.get("created_at"))

    # 2. Dependencies (Commit & User)
    sha = deployment.get("sha")
    commit_id = None

    dep_proxy = ObjectInstance(object_id=dep_id, object_type="Deployment")

    if sha:
        commit_id = ensure_commit(builder, repo_id, sha, timestamp=ts_created)
        if commit_id:
            # O2O Relationship
            dep_proxy.add_rel(target_id=commit_id, qualifier="deploys_commit")

    creator_login = deployment.get("creator", {}).get("login")
    creator_id = ensure_user(builder, repo_id, creator_login, timestamp=ts_created)

    builder.insert_object(dep_proxy)

    # 4. Event: Deployment Created
    try:
        evt_create = Event(
            event_id=str(uuid.uuid4()),
            event_type=Activities.DEPLOYMENT_CREATED,
            time=ts_created,
            attributes={
                "environment": deployment.get("environment", "unknown"),
                "ref": deployment.get("ref", ""),
                "source": "rest_api"
            }
        )
        evt_create.add_rel(dep_id, "deployment_target")
        evt_create.add_rel(repo_id, "repository_context")
        if commit_id:
            evt_create.add_rel(commit_id, "commit_deployed")
        if creator_id:
            evt_create.add_rel(creator_id, "deployment_creator")

        builder.insert_event(evt_create)
    except Exception as e:
        logger.error(f"Failed to create deployment created event: {e}")

    # 5. Process Deployment Statuses
    # We only take the latest status usually, or iterate if historical data is available
    statuses = deployment.get("statuses", [])

    if statuses:
        latest_status = statuses[0]
        state = latest_status.get("state", "pending")

        ts_updated = safe_timestamp(
            latest_status.get("updated_at"),
            fallback=latest_status.get("created_at")
        )

        activity_map = {
            "success": Activities.DEPLOYMENT_SUCCEEDED,
            "failure": Activities.DEPLOYMENT_FAILED,
            "error": Activities.DEPLOYMENT_ERROR
        }

        activity = activity_map.get(state)

        if activity:
            try:
                evt_status = Event(
                    event_id=str(uuid.uuid4()),
                    event_type=activity,
                    time=ts_updated,
                    attributes={
                        "state": state,
                        "environment": deployment.get("environment", "unknown"),
                        "description": latest_status.get("description", "")[:255]
                    }
                )
                evt_status.add_rel(dep_id, "deployment_target")
                evt_status.add_rel(repo_id, "repository_context")
                if commit_id:
                    evt_status.add_rel(commit_id, "commit_deployed")

                builder.insert_event(evt_status)
            except Exception as e:
                logger.error(f"Failed to create deployment status event: {e}")