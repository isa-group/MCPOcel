import uuid
from typing import Dict, Any
from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.helper import safe_timestamp
from github2ocel.transform.utils.ensure import ensure_user, ensure_commit, ensure_deployment
from shared.ocel.model.models  import ObjectInstance, Event
from github2ocel.transform.utils.activity import Activities

def process_deployment_graphql(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Map a GraphQL deployment to OCEL 2.0.
    """
    dep_id = ensure_deployment(builder, repo_id, node)
    if not dep_id:
        return
    
    ts_created = safe_timestamp(node.get("createdAt"))
    env_name = node.get("environment", "unknown")

    # Commit and User
    commit_oid = node.get("commit", {}).get("oid")

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

    evt = Event(
        event_id=str(uuid.uuid4()),
        event_type=Activities.DEPLOYMENT_CREATED,
        time=ts_created,
        attributes={
            "environment": env_name,
            "source": "graphql"
        }
    )
    evt.add_rel(dep_id, "created_item")
    if user_id: evt.add_rel(user_id, "creator")
    builder.insert_event(evt)

    # Event (Success/Failure)
    statuses = node.get("statuses", {}).get("nodes", [])
    for status in statuses:
        state = status.get("state", "").upper()
        status_ts = safe_timestamp(status.get("createdAt"))
        
        event_type = None
        if state == "SUCCESS":
            event_type = "DeploymentSucceeded"
        elif state in ["FAILURE", "ERROR"]:
            event_type = "DeploymentFailed"
            
        if event_type:
            status_evt = Event(
                event_id=str(uuid.uuid4()),
                event_type=event_type,
                time=status_ts,
                attributes={
                    "description": status.get("description", ""),
                    "state": state
                }
            )
            status_evt.add_rel(dep_id, "subject")
            builder.insert_event(status_evt)