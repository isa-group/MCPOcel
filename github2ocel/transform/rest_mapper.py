import logging
from datetime import datetime
from typing import Dict, Any

from github2ocel.transform.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, calculate_duration, parse_commit_message
from github2ocel.transform.utils.ensure_object import ensure_user, ensure_file, ensure_commit
from github2ocel.transform.utils.activity import Activities

logger = logging.getLogger(__name__)

# Commit Mapper (REST)
def process_commit_rest(commit: Dict[str, Any], builder: OCELBuilder,
                        repo_id: str) -> None:
    """
    Process a commit from REST API.
    Validates required fields and handles missing data.
    """
    sha = commit.get("sha")
    if not sha:
        logger.warning("Skipping commit without SHA")
        return

    message = commit.get("commit", {}).get("message", "")
    commit_id = ensure_commit(builder, repo_id, sha, message)

    if not commit_id:
        logger.error(f"Failed to ensure commit object for SHA {sha}")
        return

    builder.add_object_relationship(commit_id, repo_id, "contained_in")

    author_id = ensure_user(builder, commit.get("author", {}).get("login"))

    rels = [
        builder.rel(commit_id, "target"),
        builder.rel(repo_id, "source")
    ]
    if author_id:
        builder.add_object_relationship(commit_id, author_id, "authored_by")
        rels.append(builder.rel(author_id, "author"))

    # Process files
    files_changed = 0
    for f in commit.get("files", []):
        if not f.get("filename"):
            continue

        fid = ensure_file(builder, repo_id, f["filename"])
        if fid:
            builder.add_object_relationship(commit_id, fid, "modifies")
            rels.append(builder.rel(fid, "file"))
            files_changed += 1

    # Build event attributes
    stats = commit.get("stats", {})
    git_timestamp = commit.get("commit", {}).get("author", {}).get("date")

    if not git_timestamp:
        logger.warning(f"Commit {sha} missing timestamp, using current time")
        git_timestamp = datetime.now().isoformat() + "Z"

    event_attrs = {
        "additions": stats.get("additions", 0),
        "deletions": stats.get("deletions", 0),
        "files_changed": files_changed,
        **parse_commit_message(message)
    }

    try:
        builder.add_event(
            Activities.COMMIT_CREATED,
            git_timestamp,
            rels,
            event_attrs
        )
    except Exception as e:
        logger.error(f"Failed to create event for commit {sha}: {e}")


# Workflow Run Mapper
def process_workflow_run(run: Dict[str, Any], builder: OCELBuilder,
                        repo_id: str) -> None:
    """
    Process a workflow run from REST API.
    Validates required fields and calculates duration.
    """
    if not run.get("id"):
        logger.warning("Skipping workflow run without ID")
        return

    try:
        run_id = make_id(repo_id, "workflow", run["id"])
    except ValueError as e:
        logger.error(f"Failed to create workflow run ID: {e}")
        return

    builder.add_object(run_id, "WorkflowRun", {
        "run_id": str(run["id"]),
        "name": run.get("name", "Unknown Workflow"),
        "conclusion": run.get("conclusion", "pending")
    })

    # Ensure commit exists
    head_sha = run.get("head_sha")
    commit_id = None
    if head_sha:
        commit_id = ensure_commit(builder, repo_id, head_sha)

    actor_id = ensure_user(builder, run.get("actor", {}).get("login"))

    rels = [
        builder.rel(run_id, "target"),
        builder.rel(repo_id, "source")
    ]

    if commit_id:
        builder.add_object_relationship(run_id, commit_id, "triggered_by")
        rels.append(builder.rel(commit_id, "trigger"))

    if actor_id:
        rels.append(builder.rel(actor_id, "actor"))

    # Workflow started event
    if run.get("run_started_at"):
        try:
            builder.add_event(
                Activities.WORKFLOW_STARTED,
                run["run_started_at"],
                rels
            )
        except Exception as e:
            logger.error(f"Failed to create workflow started event: {e}")

    # Workflow completed event
    if run.get("status") == "completed" and run.get("updated_at"):
        duration = calculate_duration(
            run.get("run_started_at"),
            run.get("updated_at")
        )

        try:
            builder.add_event(
                Activities.WORKFLOW_COMPLETED,
                run["updated_at"],
                rels,
                {
                    "conclusion": run.get("conclusion", "unknown"),
                    "duration_seconds": duration
                }
            )
        except Exception as e:
            logger.error(f"Failed to create workflow completed event: {e}")


# Release Mapper
def process_release(release: Dict[str, Any], builder: OCELBuilder,
                   repo_id: str) -> None:
    """
    Process a release from REST API.
    Validates required fields.
    """
    if not release.get("id"):
        logger.warning("Skipping release without ID")
        return

    try:
        rel_id = make_id(repo_id, "release", release["id"])
    except ValueError as e:
        logger.error(f"Failed to create release ID: {e}")
        return

    builder.add_object(rel_id, "Release", {
        "tag_name": release.get("tag_name", ""),
        "name": release.get("name", ""),
        "prerelease": bool(release.get("prerelease", False))
    })

    author_id = ensure_user(builder, release.get("author", {}).get("login"))

    rels = [
        builder.rel(rel_id, "target"),
        builder.rel(repo_id, "source")
    ]
    if author_id:
        rels.append(builder.rel(author_id, "author"))

    published_at = release.get("published_at") or release.get("created_at")
    if not published_at:
        logger.warning(f"Release {release['id']} missing timestamp")
        published_at = datetime.now().isoformat() + "Z"

    try:
        builder.add_event(
            Activities.RELEASE_CREATED,
            published_at,
            rels,
            {"tag": release.get("tag_name", "")}
        )
    except Exception as e:
        logger.error(f"Failed to create release event: {e}")