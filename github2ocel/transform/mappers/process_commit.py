from typing import Dict, Any

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, parse_commit_message, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_file, ensure_user, ensure_commit_full
from github2ocel.transform.utils.activity import Activities
from shared.ocel.model.models import ObjectInstance
from shared.logger import get_logger

logger = get_logger(__name__)


def process_commit_graphql(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Process a commit from the GraphQL API with OCEL 2.0 compliance.

    Object creation is delegated to ensure_commit_full(), which writes the
    rich analytical snapshot and handles the case where a stub already exists
    (inserted by process_branch / process_deployment / process_workflow_run).

    This mapper is responsible for the domain-level relationships and events
    that require the full commit payload: file links, issue refs, CommitCreated.
    """
    author_wrapper = node.get("author") or {}
    user_node      = author_wrapper.get("user") or {}

    author_login = (
        user_node.get("login")
        or author_wrapper.get("name")
        or None
    )

    sha = node.get("oid")
    if not sha:
        logger.warning("Commit node missing OID. Skipping.")
        return

    ts      = safe_timestamp(node.get("committedDate"))
    message = node.get("message", "")

    # 1. Insert / enrich the Commit object (handles stub-over case)
    commit_id = ensure_commit_full(
        builder       = builder,
        repo_id       = repo_id,
        sha           = sha,
        committed_date= node.get("committedDate", ""),
        additions     = node.get("additions", 0),
        deletions     = node.get("deletions", 0),
        changed_files = node.get("changedFilesIfAvailable", 0),
        message       = message,
        author_login  = author_login or "",
    )
    if not commit_id:
        return

    # 2. Parse message for cross-references
    analysis = parse_commit_message(message)

    # 3. Commit -> Issue O2O (from commit message refs like "Fixes #42")
    commit_proxy = ObjectInstance(object_id=commit_id, object_type="Commit")
    has_extra_rels = False

    for issue_num in analysis.get("issue_refs", []):
        try:
            issue_id = make_id(repo_id, "issue", issue_num)
            if builder.object_exists(issue_id):
                commit_proxy.add_rel(target_id=issue_id, qualifier="references_issue")
                has_extra_rels = True
        except Exception as e:
            logger.warning(f"Failed to link commit {sha} to issue {issue_num}: {e}")

    # 4. Commit -> File O2O
    files_wrapper = node.get("files") or {}
    file_nodes    = files_wrapper.get("nodes") or []
    affected_file_ids = []

    for f in file_nodes:
        filename = f.get("path")
        if not filename:
            continue

        fid = ensure_file(builder, repo_id, filename, timestamp=ts)
        if not fid:
            continue

        status = f.get("changeType", "MODIFIED").lower()
        commit_proxy.add_rel(target_id=fid, qualifier=f"modifies_file_{status}")
        affected_file_ids.append(fid)
        has_extra_rels = True

    if has_extra_rels:
        builder.insert_object(commit_proxy)

    # 5. Author User object
    author_id = ensure_user(builder, repo_id, author_login, timestamp=ts)

    # 6. CommitCreated event
    signature    = node.get("signature") or {}
    check_suites = node.get("checkSuites", {}).get("nodes", [])

    relationships = [
        (commit_id, "created_item"),
        (repo_id,   "repository_context"),
    ]
    if author_id:
        relationships.append((author_id, "committer"))
    relationships.extend(
        (fid, "file_affected") for fid in affected_file_ids[:50]
    )

    create_event(
        builder    = builder,
        event_type = Activities.COMMIT_CREATED,
        ts         = ts,
        attributes = {
            "source":        "graphql_api",
            "intent":        analysis.get("commit_type", ""),
            "files_count":   len(file_nodes),
            "is_verified":   int(signature.get("isValid", False)),
            "ci_conclusion": check_suites[0].get("conclusion") if check_suites else None,
        },
        relationships=relationships,
    )