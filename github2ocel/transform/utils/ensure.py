import logging
import uuid
from typing import Any, Dict, Optional
from .helper import make_id, parse_commit_message, safe_timestamp
from github2ocel.transform.model.models import ObjectInstance

logger = logging.getLogger(__name__)

def ensure_user(builder, repo_id: str, login: str, timestamp: str = None) -> Optional[str]:
    """
    Registers a User object.
    timestamp: When was this user observed? (Required for OCEL 2.0 order)
    """
    if not login:
        return None

    # Normalise timestamp or use fallback (start of time)
    ts = safe_timestamp(timestamp, fallback="1970-01-01T00:00:00Z")

    user_id = make_id(repo_id, "user", login)

    user = ObjectInstance(object_id=user_id, object_type="User")
    user.add_snapshot(time=ts, attributes={"login": login})
    builder.insert_object(user)

    return user_id

def ensure_label(
    builder,
    repo_id: str,
    lbl: dict,
    timestamp: str = None) -> Optional[str]:
    """
    Register a Label object.
    Priority ID: GitHub Node ID > Label Name.
    """
    node_id = lbl.get("id")
    name = lbl.get("name")

    if not node_id and not name:
        return None

    ts = safe_timestamp(timestamp, fallback="1970-01-01T00:00:00Z")

    if node_id:
        label_id = make_id(repo_id, "label", node_id)
    else:
        label_id = make_id(repo_id, "label", name)

    label_obj = ObjectInstance(object_id=label_id, object_type="Label")
    label_obj.add_snapshot(time=ts, attributes={
        "name": name,
        "color": lbl.get("color", ""),
        "description": lbl.get("description", "")
    })

    builder.insert_object(label_obj)

    return label_id

def ensure_commit(
    builder,
    repo_id: str,
    sha: str,
    timestamp: str = None,
    message: str = "",
    source: str = "rest") -> Optional[str]:
    """
    Ensures a commit object exists.
    In OCEL 2.0, calling this multiple times creates 'versions' of the object
    or reaffirms its existence at a point in time.
    """
    if not sha or not isinstance(sha, str):
        return None

    commit_id = make_id(repo_id, "commit", sha)
    ts = safe_timestamp(timestamp, fallback="1970-01-01T00:00:00Z")

    attrs = {
        "sha": sha,
        "source": source,
    }

    if message:
        # Enrich with semantic analysis
        analysis = parse_commit_message(message)
        attrs.update({
            "intent_type": analysis.get("commit_type", "unknown"),
            "norm_compliant": int(analysis.get("is_strict_compliance", False)), # SQLite int boolean
            "is_breaking": int(analysis.get("is_breaking", False)),
            "message_full": message[:500] # Truncate to save space
        })

    commit_obj = ObjectInstance(object_id=commit_id, object_type="Commit")
    commit_obj.add_snapshot(time=ts, attributes=attrs)
    # Optional: Link Commit to Repo (O2O)
    commit_obj.add_rel(target_id=repo_id, qualifier="belongs_to")
    builder.insert_object(commit_obj)

    return commit_id

def ensure_file(builder, repo_id: str, filename: str, timestamp: str = None) -> Optional[str]:
    if not filename:
        return None

    file_id = make_id(repo_id, "file", filename)
    ts = safe_timestamp(timestamp, fallback="1970-01-01T00:00:00Z")

    file_obj = ObjectInstance(object_id=file_id, object_type="File")
    file_obj.add_snapshot(time=ts, attributes={"name": filename})
    builder.insert_object(file_obj)

    return file_id

def ensure_comment(builder, repo_id: str, comment: Dict[str, Any]) -> Optional[str]:
    """Ensure comment object exists."""
    if not comment:
        return None

    raw_id = comment.get("id") or comment.get("createdAt", uuid.uuid4().hex[:8])
    comment_id = make_id(repo_id, "comment", raw_id)

    # Dates
    created_at = safe_timestamp(comment.get("createdAt"))
    updated_at = safe_timestamp(comment.get("lastEditedAt"), fallback=created_at)

    # OCEL 2.0, use the update date as the ‘effective’ date of this version of the object
    effective_time = updated_at or created_at

    comment_obj = ObjectInstance(object_id=comment_id, object_type="Comment")
    comment_obj.add_snapshot(time=effective_time, attributes={
        "body": comment.get("body", "")[:500],
        "created_at": created_at,
        "status": "created" if created_at == updated_at else "edited"
    })

    builder.insert_object(comment_obj)

    return comment_id

def ensure_review_comment(builder, repo_id: str, comment: Dict[str, Any]) -> Optional[str]:
    if not comment or not comment.get("id"):
        return None

    comment_id = make_id(repo_id, "review_comment", comment["id"])
    created_at = comment.get("createdAt") or comment.get("created_at")
    ts = safe_timestamp(created_at, fallback="1970-01-01T00:00:00Z")

    rc_obj = ObjectInstance(object_id=comment_id, object_type="ReviewComment")
    rc_obj.add_snapshot(time=ts, attributes={
        "path": comment.get("path", ""),
        "position": int(comment.get("position", 0) or 0),
        "body": comment.get("body", "")[:200]
    })

    builder.insert_object(rc_obj)

    return comment_id

def ensure_deployment(builder, repo_id: str, deployment: Dict[str, Any]) -> Optional[str]:
    if not deployment or not deployment.get("id"):
        return None

    deployment_id = make_id(repo_id, "deployment", deployment["id"])

    # Try to get a deployment date, if not, now/fallback.
    created_at = deployment.get("created_at") or deployment.get("createdAt")
    ts = safe_timestamp(created_at, fallback="1970-01-01T00:00:00Z")

    dep_obj = ObjectInstance(object_id=deployment_id, object_type="Deployment")
    dep_obj.add_snapshot(time=ts, attributes={
        "environment": deployment.get("environment", "unknown"),
        "ref": deployment.get("ref", ""),
        "sha": deployment.get("sha", ""),
        "description": deployment.get("description", "")
    })
    # O2O: Deployment -> Repo
    dep_obj.add_rel(repo_id, "deployed_to")

    builder.insert_object(dep_obj)

    return deployment_id

def get_node_type(node: Dict[str, Any]) -> str:
    node_type = node.get("__type")
    if node_type not in {"Issue", "PullRequest"}:
        # Fallback in case the GraphQL query did not return __type
        if "pullRequest" in node or "mergedAt" in node: return "PullRequest"
        if "state" in node: return "Issue" # Generic fallback
        raise ValueError(f"Nodo inválido o tipo no soportado: {node}")
    return node_type

def is_pull_request(node: Dict[str, Any]) -> bool:
    return get_node_type(node) == "PullRequest"