import logging
from typing import Dict, Any
import uuid

from github2ocel.transform.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, parse_commit_message, safe_timestamp
from github2ocel.transform.utils.ensure import ensure_file, ensure_user
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.model.models import Event, ObjectInstance

logger = logging.getLogger(__name__)

def process_commit_rest(commit: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Process a commit from REST API with OCEL 2.0 compliance.
    """
    # 1. Identity Extraction
    commit_data = commit.get("commit", {})
    author_node = commit.get("author") or {}
    author_git = commit_data.get("author") or {}

    author_login = (
        author_node.get("login")
        or author_git.get("name")
        or "unknown_author"
    )

    # 2. Technical & Graph Metadata
    sha = commit.get("sha")
    if not sha:
        logger.warning("Commit node missing SHA. Skipping.")
        return

    # IMPORTANT: OCEL 2.0 requires precise timing.
    ts = safe_timestamp(author_git.get("date"))
    verification = commit_data.get("verification", {})
    parents = commit.get("parents", [])
    is_merge = len(parents) > 1

    # 3. Deterministic IDs
    try:
        commit_id = make_id(repo_id, "commit", sha)
    except ValueError:
        return

    # 4. Semantic Intent Analysis
    message = commit_data.get("message", "")
    analysis = parse_commit_message(message)

    logger.debug(f"Processing commit {sha[:7]} by {author_login}")

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

            # Technical attributes
            "is_verified": int(verification.get("verified", False)),
            "is_merge": int(is_merge),
            "parent_count": len(parents)
        }
    )

    # Commit -> Repository
    commit_obj.add_rel(target_id=repo_id, qualifier="contained_in")

    # Relationships (Commit -> Issue)
    for issue_num in analysis["issue_refs"]:
        try:
            issue_id = make_id(repo_id, "issue", issue_num)
            commit_obj.add_rel(target_id=issue_id, qualifier="references_issue")
        except Exception:
            pass

    # Files & Event
    files = commit.get("files", [])
    affected_file_ids = []

    for f in files:
        filename = f.get("filename")
        if not filename:
            continue

        # ensure_file ahora pide timestamp
        fid = ensure_file(builder, repo_id, filename, timestamp=ts)

        if fid:
            status = f.get("status", "modified")
            # commit -> File modified
            commit_obj.add_rel(target_id=fid, qualifier=f"modifies_file_{status}")
            affected_file_ids.append(fid)

    builder.insert_object(commit_obj)

    author_id = ensure_user(builder, repo_id, author_login, timestamp=ts)

    # Enriched Event Creation
    try:
        evt = Event(
            event_id=str(uuid.uuid4()),
            event_type=Activities.COMMIT_CREATED,
            time=ts,
            attributes={
                "source": "rest_api",
                "intent": analysis["commit_type"],
                "additions": commit.get("stats", {}).get("additions", 0),
                "deletions": commit.get("stats", {}).get("deletions", 0),
                "files_count": len(files)
            }
        )

        evt.add_rel(commit_id, "created_item")
        evt.add_rel(repo_id, "repository_context")

        if author_id:
            evt.add_rel(author_id, "committer")

        # Optional: Link the event to the affected files.
        # Limited to 50 files to avoid massive commits.
        for fid in affected_file_ids[:50]:
            evt.add_rel(fid, "file_affected")

        builder.insert_event(evt)
    except Exception as e:
        logger.error(f"Failed to record event for commit {sha[:7]}: {e}", exc_info=True)





def process_commit_graphql(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Process a commit from Graphql API with OCEL 2.0 compliance.
    """

    author_wrapper = node.get("author") or {} 
    user_node = author_wrapper.get("user") or {}
    
    author_login = (
        user_node.get("login") 
        or author_wrapper.get("name") 
        or "unknown_author"
    )

    # 2. Technical & Graph Metadata
    sha = node.get("oid")
    if not sha:
        logger.warning("Commit node missing OID. Skipping.")
        return

    # IMPORTANT: OCEL 2.0 requires precise timing.
    ts = safe_timestamp(node.get("committedDate"))

    # 3. Deterministic IDs
    try:
        commit_id = make_id(repo_id, "commit", sha)
    except ValueError:
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
            "deletions": node.get("deletions", 0)
        }
    )

    # Commit -> Repository
    commit_obj.add_rel(target_id=repo_id, qualifier="contained_in")

    # Relationships (Commit -> Issue)
    for issue_num in analysis["issue_refs"]:
        try:
            issue_id = make_id(repo_id, "issue", issue_num)
            commit_obj.add_rel(target_id=issue_id, qualifier="references_issue")
        except Exception:
            pass

    # Files & Event
    builder.insert_object(commit_obj)

    author_id = ensure_user(builder, repo_id, author_login, timestamp=ts)

    # Enriched Event Creation
    try:
        signature = node.get("signature") or {}
        check_suites_wrapper = node.get("checkSuites") or {}
        check_suites_nodes = check_suites_wrapper.get("nodes") or []
        
        evt = Event(
            event_id=str(uuid.uuid4()),
            event_type=Activities.COMMIT_CREATED,
            time=ts,
            attributes={
                "source": "graphql_api",
                "intent": analysis["commit_type"],
                "files_count": node.get("changedFilesIfAvailable", 0),
                "verification": signature.get("isValid", False)
            }
        )

        evt.add_rel(commit_id, "created_item")
        evt.add_rel(repo_id, "repository_context")

        if author_id:
            evt.add_rel(author_id, "committer")

        check_suites = node.get("checkSuites", {}).get("nodes", [])
        if check_suites:
            status = check_suites[0].get("conclusion") or check_suites[0].get("status")
            if status:
                evt.attributes["ci_conclusion"] = status

        builder.insert_event(evt)
    except Exception as e:
        logger.error(f"Failed to record event for commit {sha[:7]}: {e}", exc_info=True)
