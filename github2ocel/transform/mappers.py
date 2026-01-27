import logging
import re
from datetime import datetime
from typing import Optional, Dict, List, Any

from .builder import OCELBuilder

logger = logging.getLogger(__name__)


# Constants for Activity Names
class Activities:
    """Registry of all Activity names used in the log."""
    ISSUE_OPENED = "IssueOpened"
    ISSUE_CLOSED = "IssueClosed"
    ISSUE_COMMENT = "IssueCommented"

    PR_OPENED = "PROpened"
    PR_MERGED = "PRMerged"
    PR_CLOSED = "PRClosed"
    PR_REVIEW = "PRReviewSubmitted"
    PR_COMMENT = "PRCommented"

    COMMIT_CREATED = "CommitCreated"

    WORKFLOW_STARTED = "WorkflowRunStarted"
    WORKFLOW_COMPLETED = "WorkflowRunCompleted"

    RELEASE_CREATED = "ReleaseCreated"


# Conventional Commit Parser
CC_PATTERN = re.compile(
    r"^(?P<type>\w+)"  # Type (feat, fix...)
    r"(?:\((?P<scope>[^)]+)\))?"  # Optional scope
    r"(?P<breaking>!)?"  # Breaking change flag
    r":\s+(?P<desc>.+)$"  # Description
)


def _parse_conventional_commit(message: str) -> Dict[str, Any]:
    if not message:
        return {"cc_valid": False}

    header = message.split("\n")[0].strip()
    match = CC_PATTERN.match(header)

    if not match:
        return {
            "cc_valid": False,
            "cc_type": None,
            "cc_scope": None,
            "cc_breaking": False
        }

    data = match.groupdict()
    return {
        "cc_valid": True,
        "cc_type": data["type"].lower(),
        "cc_scope": data["scope"],
        "cc_breaking": bool(data["breaking"])
    }

# Utility Functions
def make_id(*parts: Any) -> str:
    cleaned = []
    for p in parts:
        if p is None:
            continue
        s = str(p).replace(" ", "_").replace("/", "_").replace(":", "")
        cleaned.append(s)
    return "_".join(cleaned)


def parse_time(iso_str: Optional[str]) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError:
        logger.warning(f"Failed to parse timestamp: {iso_str}")
        return None


# Object Ensurers
def ensure_user(builder: OCELBuilder, login: Optional[str]) -> Optional[str]:
    if not login:
        return None
    user_id = make_id("user", login)
    builder.add_object(user_id, "User", {"login": login})
    return user_id


def ensure_file(builder: OCELBuilder, repo_id: str, path: str) -> str:
    file_id = make_id(repo_id, "file", path)
    builder.add_object(file_id, "File", {"path": path})
    return file_id


def ensure_label(builder: OCELBuilder, repo_id: str, label: Dict[str, Any]) -> str:
    label_id = make_id(repo_id, "label", label["name"].lower())
    builder.add_object(label_id, "Label", {"name": label["name"], "color": label["color"]})
    return label_id


def ensure_commit(builder: OCELBuilder, repo_id: str, sha: str, source: str = "rest") -> str:
    commit_id = make_id(repo_id, "commit", sha)
    builder.add_object(commit_id, "Commit", {"sha": sha, "source": source})
    return commit_id


def ensure_issue_object(builder: OCELBuilder, repo_id: str, issue_data: Dict[str, Any]) -> str:
    issue_id = make_id(repo_id, "issue", issue_data["number"])
    builder.add_object(
        issue_id, "Issue",
        {
            "number": issue_data["number"],
            "state": issue_data["state"],
            "title": issue_data["title"],
            "created_at": issue_data.get("createdAt"),
            "closed_at": issue_data.get("closedAt")
        }
    )
    return issue_id


def ensure_pr_object(builder: OCELBuilder, repo_id: str, pr_data: Dict[str, Any], is_stub: bool = False) -> str:
    pr_id = make_id(repo_id, "pr", pr_data["number"])
    attributes = {
        "number": pr_data["number"],
        "source": "workflow_stub" if is_stub else "graphql"
    }
    if not is_stub:
        attributes.update({
            "merged": pr_data.get("merged", False),
            "merged_at": pr_data.get("mergedAt")
        })
    builder.add_object(pr_id, "PullRequest", attributes)
    return pr_id


# Dispatcher & Graphql mappers
def process_issue_node(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    node_type = node.get("__type")
    if node_type == "Issue":
        _map_issue(node, builder, repo_id)
    elif node_type == "PullRequest":
        _map_pull_request(node, builder, repo_id)
    else:
        # Fallback heuristic
        if node.get("merged") is not None or "mergedAt" in node:
            _map_pull_request(node, builder, repo_id)
        else:
            _map_issue(node, builder, repo_id)


def _process_common_relations(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> List[str]:
    related = []
    if author_id := ensure_user(builder, node.get("author", {}).get("login") if node.get("author") else None):
        related.append(author_id)
    for label in node.get("labels", {}).get("nodes", []):
        if label:
            related.append(ensure_label(builder, repo_id, label))
    return related


def _map_issue(issue: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    issue_id = ensure_issue_object(builder, repo_id, issue)
    related = [issue_id, repo_id] + _process_common_relations(issue, builder, repo_id)
    builder.add_event(Activities.ISSUE_OPENED, issue["createdAt"], related)
    if issue.get("closedAt"):
        builder.add_event(Activities.ISSUE_CLOSED, issue["closedAt"], related, {"state": issue["state"]})


def _map_pull_request(pr: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    pr_id = ensure_pr_object(builder, repo_id, pr)
    related = [pr_id, repo_id] + _process_common_relations(pr, builder, repo_id)
    builder.add_event(Activities.PR_OPENED, pr["createdAt"], related)
    if pr.get("merged") and pr.get("mergedAt"):
        builder.add_event(Activities.PR_MERGED, pr["mergedAt"], related)
    elif pr.get("closedAt"):
        builder.add_event(Activities.PR_CLOSED, pr["closedAt"], related, {"state": pr["state"]})
    for review in pr.get("reviews", {}).get("nodes", []):
        if not review or review.get("state") == "PENDING":
            continue
        if reviewer_id := ensure_user(builder, review.get("author", {}).get("login")):
            builder.add_event(
                Activities.PR_REVIEW,
                review.get("submittedAt"),
                [pr_id, repo_id, reviewer_id],
                {"state": review["state"]}
            )


# REST mappers
def process_workflow_run(run: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    run_id = make_id(repo_id, "workflow", run["id"])
    builder.add_object(
        run_id, "WorkflowRun",
        {"run_id": str(run["id"]), "name": run.get("name", "Unknown"), "conclusion": run.get("conclusion")}
    )
    commit_id = ensure_commit(builder, repo_id, run["head_sha"], source="workflow_inferred")
    related = [run_id, repo_id, commit_id]
    if actor_id := ensure_user(builder, run.get("actor", {}).get("login")):
        related.append(actor_id)
    for pr_stub in run.get("pull_requests", []):
        if pr_num := pr_stub.get("number"):
            related.append(ensure_pr_object(builder, repo_id, {"number": pr_num}, is_stub=True))

    if run.get("run_started_at"):
        builder.add_event(Activities.WORKFLOW_STARTED, run["run_started_at"], related)

    if run.get("updated_at") and run.get("status") == "completed":
        start = parse_time(run.get("run_started_at"))
        end = parse_time(run.get("updated_at"))
        duration = (end - start).total_seconds() if start and end else None
        builder.add_event(
            Activities.WORKFLOW_COMPLETED,
            run["updated_at"],
            related,
            {"conclusion": run.get("conclusion"), "duration_seconds": duration}
        )


def process_commit_rest(commit: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Processes a REST commit and injects Conventional Commits attributes.
    """
    sha = commit["sha"]
    commit_id = ensure_commit(builder, repo_id, sha)

    gh_author = commit.get("author") or {}
    related = [commit_id, repo_id]

    if author_id := ensure_user(builder, gh_author.get("login")):
        related.append(author_id)

    files_changed = 0
    for file in commit.get("files", []):
        related.append(ensure_file(builder, repo_id, file["filename"]))
        files_changed += 1

    git_timestamp = commit.get("commit", {}).get("author", {}).get("date")
    stats = commit.get("stats", {})

    # Extracting Attributes from Conventional Commits
    raw_message = commit.get("commit", {}).get("message", "")
    cc_attrs = _parse_conventional_commit(raw_message)

    if git_timestamp:
        builder.add_event(
            Activities.COMMIT_CREATED,
            git_timestamp,
            related,
            {
                "additions": stats.get("additions", 0),
                "deletions": stats.get("deletions", 0),
                "files_changed": files_changed,
                # Enriched attributes (type, scope, valid, breaking)
                **cc_attrs
            }
        )


def process_release(release: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """Map a GitHub release."""
    # Note: Ensure that 'Release' is in OBJECT_TYPES in builder.py
    rel_id = make_id(repo_id, "release", release["id"])

    builder.add_object(
        rel_id, "Release",
        {
            "tag_name": release.get("tag_name"),
            "name": release.get("name", ""),
            "prerelease": release.get("prerelease", False)
        }
    )

    related = [rel_id, repo_id]
    if author_id := ensure_user(builder, release.get("author", {}).get("login")):
        related.append(author_id)

    if published_at := release.get("published_at"):
        builder.add_event(Activities.RELEASE_CREATED, published_at, related)
