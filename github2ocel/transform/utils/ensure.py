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
    relationships: List[tuple] = None,
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
) -> Optional[str]:
    """
    Stub commit — creates a minimal Commit object so that O2O relationships
    (branch head, tag target, deployment SHA, workflow head_sha) can be
    registered before the full commit data is available.

    If the commit was already inserted as a stub or as a full object,
    this is a no-op (allow_update=False).  The full enrichment happens
    in ensure_commit_full(), called exclusively from process_commit_graphql
    during Phase 4.
    """
    if not sha:
        return None

    ts = safe_timestamp(timestamp, fallback="1970-01-01T00:00:00Z")

    return _ensure_object(
        builder=builder,
        repo_id=repo_id,
        obj_type="Commit",
        raw_id=sha,
        timestamp=ts,
        attributes={"sha": sha},
        relationships=[(repo_id, "belongs_to")]
    )


def ensure_commit_full(
    builder,
    repo_id: str,
    sha: str,
    committed_date: str,
    additions: int = 0,
    deletions: int = 0,
    changed_files: int = 0,
    message: str = "",
    author_login: str = "",
) -> Optional[str]:
    """
    Full commit enrichment — writes the complete analytical snapshot.

    Called exclusively from process_commit_graphql (Phase 4).
    Uses allow_update=True so the rich snapshot is always written, even
    if a stub was already inserted by process_branch / process_deployment /
    process_workflow_run in earlier phases.

    Because committedDate is used as ocel_time (different from the stub's
    timestamp which was the deployment/branch observation time), the
    composite PK (ocel_id, ocel_time, ocel_changed_field) is distinct and
    the INSERT succeeds cleanly alongside the stub snapshot.
    """
    if not sha:
        return None

    ts = safe_timestamp(committed_date, fallback="1970-01-01T00:00:00Z")

    analysis = parse_commit_message(message) if message else {}

    attrs = {
        "sha":              sha,
        "source":           "graphql",
        "additions":        additions,
        "deletions":        deletions,
        "changed_files":    changed_files,
        "cc_type":          analysis.get("commit_type", ""),
        "cc_scope":         analysis.get("scope", ""),
        "cc_subject":       analysis.get("subject", "")[:255],
        "cc_body_len":      analysis.get("body_length", 0),
        "is_breaking":      int(analysis.get("is_breaking", False)),
        "is_conventional":  int(analysis.get("is_conventional", False)),
        "author_login":     author_login or "",
    }

    return _ensure_object(
        builder=builder,
        repo_id=repo_id,
        obj_type="Commit",
        raw_id=sha,
        timestamp=ts,
        attributes=attrs,
        relationships=[(repo_id, "belongs_to")],
        allow_update=True,   # always write the full snapshot even over a stub
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
    Infers the O2O qualifier from the object type.
    Uses the builder's in-memory object_registry — no SQL needed.
    Returns None if the object is not yet known (safe: relationship is skipped).
    """
    obj_type = builder.object_registry.get(obj_id)
    if not obj_type:
        logger.debug(f"[infer_qualifier] Object {obj_id} not in registry yet — skipping rel")
        return None

    qualifier_map = {
        "PullRequest": "review_comment_of",
        "Issue":       "review_comment_of",
        "File":        "review_comment_on_file",
        "Repository":  "belongs_to",
    }
    return qualifier_map.get(obj_type)