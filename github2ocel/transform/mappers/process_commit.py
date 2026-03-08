from typing import Dict, Any

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, parse_commit_message, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_file, ensure_user
from github2ocel.transform.utils.activity import Activities
from shared.ocel.model.models  import ObjectInstance
from shared.logger import get_logger

logger = get_logger(__name__)

def process_commit_graphql(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Process a commit from Graphql API with OCEL 2.0 compliance.
    """

    author_wrapper = node.get("author") or {}
    user_node = author_wrapper.get("user") or {}

    author_login = (
        user_node.get("login")
        or author_wrapper.get("name")
        or None
    )


    # Technical & Graph Metadata
    sha = node.get("oid")
    if not sha:
        logger.warning("Commit node missing OID. Skipping.")
        return

    # IMPORTANT: OCEL 2.0 requires precise timing.
    ts = safe_timestamp(node.get("committedDate"))

    # 3. Deterministic IDs
    try:
        commit_id = make_id(repo_id, "commit", sha)
    except ValueError as e:
        logger.warning(f"Failed to create commit ID for sha={sha}: {e}")
        return

    # 4. Semantic Intent Analysis
    message = node.get("message", "")
    analysis = parse_commit_message(message)

    commit_obj = ObjectInstance(object_id=commit_id, object_type="Commit")

    # 5. Commit Object Registration (OCEL 2.0: Attributes + Time)
    commit_obj.add_snapshot(
        time=ts,
        attributes={
            "sha": sha,
            "time": ts,
            # Attributes of Conventional Commits
            "cc_type": analysis["commit_type"],     # feat, fix, chore...
            "cc_scope": analysis["scope"],          # auth, api, ui...
            "cc_subject": analysis["subject"],      # "add login button"
            "cc_body_len": analysis["body_length"], # 150 (characters)
            "is_breaking": analysis["is_breaking"], # 1 o 0
            "is_conventional": analysis["is_conventional"],
            "full_message": analysis["full_message"][:1000], # truncated for security reasons


            # More Metrics (GraphQL)
            "additions": node.get("additions", 0),
            "deletions": node.get("deletions", 0),
            "changed_files": node.get("changedFilesIfAvailable", 0),
        }
    )

    # Commit -> Repository
    commit_obj.add_rel(target_id=repo_id, qualifier="contained_in")

    # Relationships (Commit -> Issue)
    for issue_num in analysis["issue_refs"]:
        try:
            issue_id = make_id(repo_id, "issue", issue_num)
            if builder.object_exists(issue_id):
                commit_obj.add_rel(target_id=issue_id, qualifier="references_issue")
        except Exception as e:
            logger.warning(f"Failed to create issue ID for issue_num={issue_num}: {e}")
            pass

    # Relationships (Commit -> PullRequest)
    """
    for pr_num in analysis["pr_refs"]:  # Si tu parser lo detecta
        try:
            pr_id = make_id(repo_id, "pr", pr_num)
            if builder.object_exists(pr_id):
                commit_obj.add_rel(target_id=pr_id, qualifier="belongs_to_pr")
        except Exception as e:
            logger.warning(f"Failed to link commit {sha} to PR {pr_num}: {e}")
    """
    files_wrapper = node.get("files") or {}
    file_nodes = files_wrapper.get("nodes") or []

    affected_file_ids = []

    for f in file_nodes:
        filename = f.get("path")
        if not filename:
            logger.warning(f"File node missing path, skipping. File data: {f}")
            continue

        fid = ensure_file(builder, repo_id, filename, timestamp=ts)
        if not fid:
            logger.warning(f"Failed to ensure file object for filename {filename}")
            continue

        status = f.get("changeType", "MODIFIED").lower()

        # Commit -> File relation
        commit_obj.add_rel(
            target_id=fid,
            qualifier=f"modifies_file_{status}"
        )

        affected_file_ids.append(fid)

    # Files & Event
    builder.insert_object(commit_obj)

    author_id = ensure_user(builder, repo_id, author_login, timestamp=ts)

    # Enriched Event Creation
    signature = node.get("signature") or {}
    check_suites = node.get("checkSuites", {}).get("nodes", [])

    relationships = [
        (commit_id, "created_item"),
        (repo_id, "repository_context"),
    ]
    if author_id:
        relationships.append((author_id, "committer"))

    relationships.extend([
        (fid, "file_affected") for fid in affected_file_ids[:50] # Limit to 50 files
    ])

    # Filtrar None por seguridad
    relationships = [r for r in relationships if r is not None]

    create_event(
        builder=builder,
        event_type=Activities.COMMIT_CREATED,
        ts=ts,
        attributes={
            "source": "graphql_api",
            "intent": analysis["commit_type"],
            "files_count": len(file_nodes),
            "is_verified": int(signature.get("isValid", False)),
            "ci_conclusion": check_suites[0].get("conclusion") if check_suites else None
        },
        relationships=relationships
    )