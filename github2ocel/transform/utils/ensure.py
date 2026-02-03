from typing import Any, Dict, Optional
import uuid
import logging

logger = logging.getLogger(__name__)

from .helper import make_id, parse_commit_message, safe_timestamp

def ensure_user(builder, login: str) -> str:
    if not login:
        return None

    user_id = f"user_{login}"

    builder.add_object(user_id, "User", {"login": login})
    return user_id

def ensure_label(builder, repo_id: str, lbl: dict) -> str:
    name = lbl.get("name")
    if not name:
        return None

    label_id = make_id(repo_id, "label", name)
    builder.add_object(label_id, "Label", {
        "name": name,
        "color": lbl.get("color", ""),
        "description": lbl.get("description", "")
    })
    return label_id

def ensure_commit(builder, repo_id: str, sha: str,
                  message: str = "", source: str = "rest") -> Optional[str]:
    """
    Ensures a commit object exists in the Ocel model.
    If the commit already exists, it updates attributes only if new data is provided.
    """
    if not sha or not isinstance(sha, str):
        return None

    commit_id = make_id(repo_id, "commit", sha)

    existing_obj = builder.get_object(commit_id)
    if not existing_obj or (
        message and "intent_type" not in existing_obj["ovmap"]):

        attrs = {"sha": sha, "source": source}

        if message:
            # Enrich with semantic analysis
            analysis = parse_commit_message(message)
            attrs.update({
                "intent_type": analysis["commit_type"],
                "norm_compliant": analysis["norm_compliant"],
                "is_breaking": analysis["is_breaking"],
                "message_full": message
            })

        builder.add_object(commit_id, "Commit", attrs)
        status = "Updated" if existing_obj else "Created"
        logger.debug(f"{status} commit object: {sha[:7]} (Source: {source})")

    return commit_id


def ensure_file(builder, repo_id, filename):
    if not filename:
        return None

    file_id = make_id(repo_id, "file", filename)
    builder.add_object(file_id, "File", {"name": filename})
    return file_id


def ensure_comment(builder, repo_id: str, comment: Dict[str, Any]) -> Optional[str]:
    """Ensure comment object exists. Returns None if comment data is invalid."""
    if not comment:
        return None

    raw_id = comment.get("id") or comment.get("createdAt", uuid.uuid4().hex[:8])

    comment_id = make_id(repo_id, "comment", raw_id)

    created_at = safe_timestamp(comment.get("createdAt"))
    updated_at = safe_timestamp(comment.get("lastEditedAt"), fallback=created_at)

    builder.add_object(comment_id, "Comment", {
        "body": comment.get("body", ""),
        "created_at": created_at,
        "updated_at": updated_at or created_at,
        "status": "created"
    })

    return comment_id


def ensure_review_comment(
    builder,
    repo_id: str,
    comment: Dict[str, Any]
) -> Optional[str]:
    """Ensure review comment object exists."""
    if not comment or not comment.get("id"):
        return None

    comment_id = make_id(repo_id, "review_comment", comment["id"])

    builder.add_object(comment_id, "ReviewComment", {
        "path": comment.get("path", ""),
        "position": comment.get("position", 0),
        "body": comment.get("body", "")[:200],
        "created_at": comment.get("createdAt") or comment.get("created_at", "")
    })

    return comment_id


def ensure_deployment(
    builder,
    repo_id: str,
    deployment: Dict[str, Any]
) -> Optional[str]:
    """Ensure deployment object exists."""
    if not deployment or not deployment.get("id"):
        return None

    deployment_id = make_id(repo_id, "deployment", deployment["id"])

    builder.add_object(deployment_id, "Deployment", {
        "environment": deployment.get("environment", "unknown"),
        "ref": deployment.get("ref", ""),
        "sha": deployment.get("sha", ""),
        "description": deployment.get("description", "")
    })

    return deployment_id


def get_node_type(node: Dict[str, Any]) -> str:
    """
    Returns the node type (Issue/PullRequest) by validating the contract with the fetcher.
    Throws ValueError if the type is not supported.
    """
    node_type = node.get("__type")
    if node_type not in {"Issue", "PullRequest"}:
        raise ValueError(f"Nodo inválido o tipo no soportado: {node_type}")
    return node_type


def is_pull_request(node: Dict[str, Any]) -> bool:
    """Fast Boolean validator for conditional logic."""
    return get_node_type(node) == "PullRequest"