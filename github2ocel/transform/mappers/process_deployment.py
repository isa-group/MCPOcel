import logging
from typing import Dict, Any

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user, ensure_commit, ensure_deployment
from shared.ocel.model.models import ObjectInstance
from github2ocel.transform.utils.activity import Activities

logger = logging.getLogger(__name__)


def process_deployment(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Map a GraphQL deployment node to OCEL 2.0.

    Objects:   Deployment
    Events:    DeploymentCreated, DeploymentSucceeded, DeploymentFailed
    O2O:       Deployment → Repo    (deployed_to)             — via ensure_deployment
               Deployment → Commit  (deploys_commit)
               Deployment → User    (created_by)
               Deployment → Branch  (deployed_from_branch)   — from ref.name
    """
    dep_id = ensure_deployment(builder, repo_id, node)
    if not dep_id:
        logger.warning(f"Failed to ensure deployment for node {node.get('id')}")
        return

    ts_created = safe_timestamp(node.get("createdAt"))
    env_name   = node.get("environment", "unknown")

    # O2O → Commit
    commit_oid = (node.get("commit") or {}).get("oid")
    commit_id  = None
    if commit_oid:
        commit_id = ensure_commit(builder, repo_id, commit_oid, timestamp=ts_created)
        if commit_id:
            proxy = ObjectInstance(object_id=dep_id, object_type="Deployment")
            proxy.add_rel(commit_id, "deploys_commit")
            builder.insert_object(proxy)

    # O2O → User (creator)
    creator_login = (node.get("creator") or {}).get("login")
    user_id = ensure_user(builder, repo_id, creator_login, timestamp=ts_created) if creator_login else None
    if user_id:
        proxy = ObjectInstance(object_id=dep_id, object_type="Deployment")
        proxy.add_rel(user_id, "created_by")
        builder.insert_object(proxy)

    # O2O → Branch (ref.name — Branch objects seeded in Phase 0)
    branch_id = None  # initialised here — used in create_event relationships below
    ref_name = (node.get("ref") or {}).get("name") if isinstance(node.get("ref"), dict) else None
    if ref_name:
        branch_id = make_id(repo_id, "branch", ref_name)
        if builder.object_exists(branch_id):
            proxy = ObjectInstance(object_id=dep_id, object_type="Deployment")
            proxy.add_rel(branch_id, "deployed_from_branch")
            builder.insert_object(proxy)

    # Event: DeploymentCreated
    create_event(
        builder=builder,
        event_type=Activities.DEPLOYMENT_CREATED,
        ts=ts_created,
        attributes={
            "environment": env_name,
            "task":        node.get("task", ""),
            "source":      "graphql",
        },
        relationships=[
            (dep_id,    "subject"),
            (repo_id,   "context"),
            (user_id,   "actor")     if user_id   else None,
            (commit_id, "on_commit") if commit_id else None,
            (branch_id, "on_branch")  if branch_id else None,
        ]
    )

    # Events: DeploymentSucceeded / DeploymentFailed (from status history)
    for status in (node.get("statuses") or {}).get("nodes") or []:
        if not status:
            continue

        state     = (status.get("state") or "").upper()
        status_ts = safe_timestamp(status.get("createdAt"))

        if not status_ts:
            continue

        if state == "SUCCESS":
            event_type = Activities.DEPLOYMENT_SUCCEEDED
        elif state == "FAILURE":
            event_type = Activities.DEPLOYMENT_FAILED
        elif state == "ERROR":
            event_type = Activities.DEPLOYMENT_ERROR
        else:
            continue

        create_event(
            builder=builder,
            event_type=event_type,
            ts=status_ts,
            attributes={
                "state":           state,
                "description":     (status.get("description") or "")[:255],
                "environment_url": status.get("environmentUrl") or "",
                "log_url":         status.get("logUrl") or "",
                "source":          "graphql",
            },
            relationships=[
                (dep_id,  "subject"),
                (repo_id, "context"),
            ]
        )