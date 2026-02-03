import logging
from typing import Dict, Any
from github2ocel.transform.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, parse_commit_message
from github2ocel.transform.utils.ensure import ensure_file, ensure_commit
from github2ocel.transform.utils.activity import Activities

logger = logging.getLogger(__name__)

def process_commit_rest(commit: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Process a commit from REST API with enriched data and detailed logging.
    """
    # 1. Identity Extraction (Ghost author fallback)
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

    verification = commit_data.get("verification", {})
    parents = commit.get("parents", [])
    is_merge = len(parents) > 1

    # 3. Deterministic IDs
    commit_id = make_id(repo_id, "commit", sha)
    author_id = make_id(repo_id, "user", author_login)

    # 4. Semantic Intent Analysis
    message = commit_data.get("message", "")
    analysis = parse_commit_message(message)

    logger.debug(f"Processing commit {sha[:7]} by {author_login}")

    # 5. Commit Object Registration (Full Technical Detail)
    builder.add_object(commit_id, "Commit", {
        "sha": sha,
        "intent_type": analysis["commit_type"],
        "norm_compliant": analysis["is_strict_compliance"],
        "is_breaking": analysis["is_breaking"],
        "is_verified": verification.get("verified", False),
        "verification_reason": verification.get("reason", "none"),
        "is_merge": is_merge,
        "parent_count": len(parents),
        "subject": analysis["subject"]
    })

    # Ensure the user object exists
    builder.add_object(author_id, "User", {"login": author_login})

    # 6. File Impact Processing
    files = commit.get("files", [])

    # Event Qualifiers: 'agent' for author, 'target' for the commit object
    event_rels = [
        builder.rel(commit_id, "target"),
        builder.rel(author_id, "agent"),
        builder.rel(repo_id, "source")
    ]

    for f in files:
        filename = f.get("filename")
        if not filename:
            continue

        fid = ensure_file(builder, repo_id, filename)
        status = f.get("status", "modified")

        # Enrich File object with delta stats
        builder.add_object(fid, "File", {
            "status": status,
            "additions": f.get("additions", 0),
            "deletions": f.get("deletions", 0)
        })

        # Qualitative relationship (action_added, action_removed, etc.)
        builder.add_object_relationship(commit_id, fid, f"action_{status}")
        event_rels.append(builder.rel(fid, "file"))

    # 7. Enriched Event Creation
    try:
        builder.add_event(
            Activities.COMMIT_CREATED,
            author_git.get("date"),
            event_rels,
            {
                "event_class": "observed",
                "confidence": "high",
                "intent": analysis["commit_type"],
                "total_additions": commit.get("stats", {}).get("additions", 0),
                "total_deletions": commit.get("stats", {}).get("deletions", 0),
                "files_count": len(files)
            }
        )
    except Exception as e:
        logger.error(f"Failed to record event for commit {sha[:7]}: {e}", exc_info=True)
