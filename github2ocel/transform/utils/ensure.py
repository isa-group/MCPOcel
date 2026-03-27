from typing import Any, Dict, Optional, List
from .helper import make_id, parse_commit_message, safe_timestamp
from shared.ocel.builder import OCELBuilder
from shared.ocel.model.models  import ObjectInstance
from shared.logger import get_logger

logger = get_logger(__name__)

def _ensure_object(
    builder: OCELBuilder,
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


def ensure_user(builder: OCELBuilder, repo_id: str, login: str, timestamp: str = None) -> Optional[str]:
    return _ensure_object(
        builder=builder,
        repo_id=repo_id,
        obj_type="User",
        raw_id=login,
        timestamp=timestamp,
        attributes={"login": login}
    )

def ensure_label(builder: OCELBuilder, repo_id: str, lbl: dict, timestamp: str = None) -> Optional[str]:
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
    builder: OCELBuilder,
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
        attributes={},
        relationships=[(repo_id, "belongs_to")]
    )


def ensure_commit_full(
    builder: OCELBuilder,
    repo_id: str,
    sha: str,
    committed_date: str,
    additions: int = 0,
    deletions: int = 0,
    changed_files: int = 0,
    message: str = "",
    author_login: str = "",
    authored_date: str = "",
    committer_login: str = "",
    is_merge_commit: bool = False,
    analysis: dict = None,
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

    Args:
        analysis: pre-computed parse_commit_message result — avoids double parsing
                  when the caller already has it. Computed here if not provided.
    """
    if not sha:
        return None

    ts = safe_timestamp(committed_date, fallback="1970-01-01T00:00:00Z")

    if analysis is None:
        analysis = parse_commit_message(message) if message else {}

    attrs = {
        "sha":              sha,
        "source":           "graphql",
        "additions":        additions,
        "deletions":        deletions,
        "changed_files":    changed_files,
        "authored_date":    safe_timestamp(authored_date) if authored_date else ts,
        "author_login":     author_login or "",
        "committer_login":  committer_login or "",
        "is_merge_commit":  int(is_merge_commit),
        "cc_type":          analysis.get("commit_type", ""),
        "cc_scope":         analysis.get("scope", ""),
        "cc_subject":       analysis.get("subject", "")[:255],
        "cc_body_len":      analysis.get("body_length", 0),
        "is_breaking":      int(analysis.get("is_breaking", False)),
        "is_conventional":  int(analysis.get("is_conventional", False)),
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


def ensure_comment(
    builder: OCELBuilder,
    repo_id: str,
    comment_id: str,
    comment_type: str,
    created_at: str,
    attributes: Dict[str, Any] = None,
    relationships: List[tuple] = None,
) -> Optional[str]:
    """
    Upsert a Comment object — merges attributes from multiple sources.

    Uses allow_update=True so the same comment can be enriched progressively:
      - Phase 2: IssueComment / PRComment (basic fields)
      - Phase 3: ReviewComment from PR_REVIEWS_QUERY (adds path, line, diffHunk)
      - Phase 3: ReviewComment from PR_THREADS_QUERY (adds replyTo, outdated, thread context)
      - Phase 7: DiscussionComment (adds isAnswer)

    The GitHub node ID is globally unique — no risk of collision across types.

    Args:
        comment_id:   GitHub node ID (e.g. "IC_kwDO...", "PRRC_kwDO...", "DC_kwDO...")
        comment_type: "issue" | "pr" | "review" | "discussion"
        created_at:   ISO timestamp string
        attributes:   snapshot attributes to merge (type-specific fields)
        relationships: O2O relationships to register
    """
    if not comment_id:
        return None

    base_attrs = {"comment_type": comment_type}
    if attributes:
        base_attrs.update(attributes)

    return _ensure_object(
        builder=builder,
        repo_id=repo_id,
        obj_type="Comment",
        raw_id=comment_id,
        timestamp=safe_timestamp(created_at, fallback="1970-01-01T00:00:00Z"),
        attributes=base_attrs,
        relationships=relationships or [],
        allow_update=True,  # upsert — multiple sources enrich the same object
    )


def ensure_deployment(builder, repo_id: str, deployment: Dict[str, Any]) -> Optional[str]:
    # Key on databaseId (integer) — consistent with process_timeline which resolves
    # DeployedEvent.deployment.databaseId via make_id(repo_id, "deployment", databaseId).
    # The GraphQL node id is opaque and not available in timeline events.
    raw_id = deployment.get("databaseId") or deployment.get("database_id") or deployment.get("id")
    if not deployment or not raw_id:
        logger.warning(f"Deployment missing id, skipping. Deployment data: {deployment}")
        return None

    created_at = deployment.get("created_at") or deployment.get("createdAt")

    return _ensure_object(
        builder=builder,
        repo_id=repo_id,
        obj_type="Deployment",
        raw_id=raw_id,
        timestamp=created_at,
        attributes={
            "environment": deployment.get("environment", "unknown"),
            "state":       deployment.get("state", ""),
            "task":        deployment.get("task", ""),
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

def ensure_team(builder: OCELBuilder, repo_id: str, team: Dict[str, Any]) -> Optional[str]:
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


def ensure_tagger(
    builder: OCELBuilder,
    repo_id: str,
    tagger_info: Dict[str, Any],
    timestamp: str,
) -> Optional[str]:
    """
    Registers the tagger as a User object.

    Priority:
      1. GitHub login (linked account)
      2. Git name + email (local git identity, no GitHub account)

    Returns the tagger object_id or None if no identity is available.
    """
    if not tagger_info:
        return None

    login = tagger_info.get("login")
    name  = tagger_info.get("name")
    email = tagger_info.get("email")

    if login:
        return ensure_user(builder, repo_id, login, timestamp=timestamp)

    # Fallback: git identity without GitHub account
    # Use email as the stable key (more unique than name)
    if email:
        raw_id = email.replace("@", "_at_").replace(".", "_")
        return _ensure_object(
            builder=builder,
            repo_id=repo_id,
            obj_type="User",
            raw_id=raw_id,
            timestamp=timestamp,
            attributes={
                "login": "",
                "git_name":  name  or "",
                "git_email": email,
            },
        )

    return None