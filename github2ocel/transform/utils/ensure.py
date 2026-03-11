from typing import Any, Dict, Optional, List
from .helper import make_id, parse_commit_message, safe_timestamp
from shared.ocel.model.models  import ObjectInstance
from shared.logger import get_logger

logger = get_logger(__name__)

def _ensure_object(
    builder,
    repo_id: str,
    obj_type: str,
    raw_id: str,
    timestamp: str = None,
    attributes: Dict[str, Any] = None,
    relationships: List[Dict[str, str]] = None,
    allow_update: bool = False,
) -> Optional[str]:
    """
    Register any object generically for OCEL 2.0.

    If the object already exists in the builder and allow_update=False (default),
    only new O2O relationships are added — no duplicate snapshot is written.
    Set allow_update=True for objects that legitimately evolve over time
    (e.g. Milestone state changes, PR status transitions).
    """
    if not raw_id:
        logger.warning(f"Skipping {obj_type} with empty raw_id")
        return None

    # 1. Unique identity
    object_id = make_id(repo_id, obj_type.lower(), str(raw_id))

    obj_instance = ObjectInstance(object_id=object_id, object_type=obj_type)

    # 2. Snapshot — only on first insert, or when explicitly allowed
    if allow_update or not builder.object_exists(object_id):
        ts = safe_timestamp(timestamp, fallback="1970-01-01T00:00:00Z")
        obj_instance.add_snapshot(time=ts, attributes=attributes or {})

    # 3. Optional O2O relationships
    if relationships:
        for target_id, qualifier in relationships:
            if target_id:
                obj_instance.add_rel(target_id, qualifier)

    builder.insert_object(obj_instance)
    return object_id


def ensure_user(builder, repo_id: str, login: str, timestamp: str = None) -> Optional[str]:
    return _ensure_object(
        builder=builder,
        repo_id=repo_id,
        obj_type="User",
        raw_id=login,
        timestamp=timestamp,
        attributes={"login": login}
    )

def ensure_label(builder, repo_id: str, lbl: dict, timestamp: str = None) -> Optional[str]:
    node_id = lbl.get("id")
    name = lbl.get("name")
    if not node_id and not name:
        return None

    raw_id = node_id or name

    return _ensure_object(
        builder=builder,
        repo_id=repo_id,
        obj_type="Label",
        raw_id=raw_id,
        timestamp=timestamp,
        attributes={
            "name": name,
            "color": lbl.get("color", ""),
            "description": lbl.get("description", "")
        }
    )

def ensure_commit(
    builder,
    repo_id: str,
    sha: str,
    timestamp: str = None,
    message: str = "",
    source: str = "rest"
) -> Optional[str]:

    if not sha:
        return None

    ts = safe_timestamp(timestamp, fallback="1970-01-01T00:00:00Z")

    attrs = {
        "sha": sha,
        "source": source,
    }

    if message:
        analysis = parse_commit_message(message)
        attrs.update({
            "intent_type": analysis.get("commit_type", "unknown"),
            "norm_compliant": int(analysis.get("is_strict_compliance", False)),
            "is_breaking": int(analysis.get("is_breaking", False)),
            "message_full": message[:500],
        })

    return _ensure_object(
        builder=builder,
        repo_id=repo_id,
        obj_type="Commit",
        raw_id=sha,
        timestamp=ts,
        attributes=attrs,
        relationships=[(repo_id, "belongs_to")]
    )


def ensure_file(builder, repo_id: str, filename: str, timestamp: str = None) -> Optional[str]:
    return _ensure_object(
        builder=builder,
        repo_id=repo_id,
        obj_type="File",
        raw_id=filename,
        timestamp=timestamp,
        attributes={"name": filename}
    )


def ensure_comment(builder, repo_id: str, comment: Dict[str, Any]) -> Optional[str]:
    if not comment:
        return None

    raw_id = comment.get("id") or comment.get("createdAt")

    created_at = safe_timestamp(comment.get("createdAt"))
    updated_at = safe_timestamp(comment.get("lastEditedAt"), fallback=created_at)
    effective_time = updated_at or created_at

    return _ensure_object(
        builder=builder,
        repo_id=repo_id,
        obj_type="Comment",
        raw_id=raw_id,
        timestamp=effective_time,
        attributes={
            "body": comment.get("body", "")[:500],
            "created_at": created_at,
            "status": "created" if created_at == updated_at else "edited"
        }
    )

def ensure_review_comment(
    builder,
    repo_id: str,
    comment: Dict[str, Any],
    related_ids: List[str] = None
) -> Optional[str]:
    if not comment or not comment.get("id"):
        logger.warning(f"Review comment missing id, skipping. Comment data: {comment}")
        return None

    created_at = comment.get("createdAt") or comment.get("created_at")

    relationships = []
    for obj_id in (related_ids or []):
        qualifier = _infer_qualifier_from_type(builder, obj_id)
        if qualifier:
            relationships.append((obj_id, qualifier))

    return _ensure_object(
        builder=builder,
        repo_id=repo_id,
        obj_type="ReviewComment",
        raw_id=comment["id"],
        timestamp=created_at,
        attributes={
            "path": comment.get("path", ""),
            "position": int(comment.get("position", 0) or 0),
            "body": comment.get("body", "")[:500]
        },
        relationships=relationships if relationships else None
    )

def ensure_deployment(builder, repo_id: str, deployment: Dict[str, Any]) -> Optional[str]:
    if not deployment or not deployment.get("id"):
        logger.warning(f"Deployment missing id, skipping. Deployment data: {deployment}")
        return None

    created_at = deployment.get("created_at") or deployment.get("createdAt")

    return _ensure_object(
        builder=builder,
        repo_id=repo_id,
        obj_type="Deployment",
        raw_id=deployment["id"],
        timestamp=created_at,
        attributes={
            "environment": deployment.get("environment", "unknown"),
            # ref can be a dict {"name": "..."} from GraphQL or a plain string from REST
            "ref": (deployment.get("ref") or {}).get("name", "")
                   if isinstance(deployment.get("ref"), dict)
                   else str(deployment.get("ref") or ""),
            "sha": (deployment.get("commit") or {}).get("oid", "")
                   or str(deployment.get("sha") or ""),
            "description": str(deployment.get("description") or "")[:255],
        },
        relationships=[(repo_id, "deployed_to")] 
    )


def ensure_team(builder, repo_id: str, team: Dict[str, Any]) -> Optional[str]:
    if not team or not team.get("name"):
        return None

    team_key = team["name"].lower().replace(" ", "_")

    return _ensure_object(
        builder=builder,
        repo_id=repo_id,
        obj_type="Team",
        raw_id=team_key,
        timestamp=team.get("createdAt"),
        attributes={"name": team["name"]}
    )

def _infer_qualifier_from_type(builder, obj_id: str) -> Optional[str]:
    """
    Infers the O2O qualifier by looking up the object type in the DB.
    Avoids hardcoding ID formats — works for any object type.
    """
    builder.cursor.execute(
        "SELECT ocel_type FROM object WHERE ocel_id = ?", (obj_id,)
    )
    row = builder.cursor.fetchone()
    if not row:
        logger.warning(f"Related object with ID {obj_id} not found in DB. Cannot infer qualifier.")
        return None

    qualifier_map = {
        "PullRequest": "review_comment_of",
        "Issue":       "review_comment_of",
        "File":        "review_comment_on_file",
        "Repository":  "belongs_to",
    }
    return qualifier_map.get(row[0])