import uuid
import logging
from typing import Dict, Any
from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.helper import safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user, ensure_commit, ensure_deployment
from shared.ocel.model.models  import ObjectInstance
from github2ocel.transform.utils.activity import Activities

logger = logging.getLogger(__name__)

def process_deployment(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Map a GraphQL deployment to OCEL 2.0.
    """
    dep_id = ensure_deployment(builder, repo_id, node)
    if not dep_id:
        logger.warning(f"Failed to ensure deployment object for node {node.get('id')}")
        return

    ts_created = safe_timestamp(node.get("createdAt"))
    env_name = node.get("environment", "unknown")

    # Commit and User
    commit_oid = (node.get("commit") or {}).get("oid")

    commit_ref_id = None
    if commit_oid:
        commit_ref_id = ensure_commit(builder, repo_id, commit_oid, timestamp=ts_created)
        if commit_ref_id:
            dep_obj = ObjectInstance(object_id=dep_id, object_type="Deployment")
            dep_obj.add_rel(commit_ref_id, "deploys_commit")
            builder.insert_object(dep_obj)

    creator_login = node.get("creator", {}).get("login")
    user_id = None
    if creator_login:
        user_id = ensure_user(builder, repo_id, creator_login, timestamp=ts_created)

    create_event(
        builder=builder,
        event_type=Activities.DEPLOYMENT_CREATED,
        ts=ts_created,
        attributes={
            "environment": env_name,
            "source": "graphql"
        },
        relationships=[
            (user_id, "deployment_creator") if user_id else None,
            (repo_id, "context"),
            (dep_id, "subject")
        ]
    )

    # Event (Success/Failure)
    statuses_data = node.get("statuses") or {}
    statuses = statuses_data.get("nodes") or []

    for status in statuses:
        if not status:
            continue

        state = status.get("state", "").upper()
        status_ts = safe_timestamp(status.get("createdAt"))

        if not status_ts:
            continue

        event_type = None
        if state == "SUCCESS":
            event_type = Activities.DEPLOYMENT_SUCCEEDED
        elif state in ["FAILURE", "ERROR"]:
            event_type = Activities.DEPLOYMENT_FAILED

        if event_type:
            create_event(
                builder=builder,
                event_type=event_type,
                ts=status_ts,
                attributes={
                    "description": status.get("description", ""),
                    "state": state,
                    "source": "graphql"
                },
                relationships=[
                    (dep_id, "subject"),
                    (repo_id, "context")
                ]
            )
