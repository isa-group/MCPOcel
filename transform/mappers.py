from .builder import OCELBuilder
from datetime import datetime

def parse_time(iso_str):
    """Parses ISO 8601 strings to datetime objects, handling 'Z' suffix."""
    if not iso_str: return None
    try:
        return datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
    except:
        return None

def process_issue_node(issue, builder: OCELBuilder, repo_id):
    """Processes GraphQL nodes containing Issues and Pull Requests."""
    issue_num = issue["number"]
    issue_id = f"issue_{issue_num}"

    # Create Issue Object
    builder.add_object(issue_id, "Issue", {
        "number": issue_num,
        "state": issue["state"],
        "title": issue["title"],
        "created_at": issue["createdAt"]
    })

    # Create User Object if author exists
    user_id = None
    if issue.get("author") and issue["author"].get("login"):
        user_login = issue["author"]["login"]
        user_id = f"user_{user_login}"
        builder.add_object(user_id, "User", {"login": user_login})


    # Labels Objects
    label_ids = []
    if "labels" in issue and issue["labels"]["nodes"]:
        for label in issue["labels"]["nodes"]:
            safe_name = label["name"].replace(" ", "_").lower()
            label_id = f"label_{safe_name}"
            builder.add_object(label_id, "Label", {
                "name": label["name"],
                "color": label["color"]
            })
            label_ids.append(label_id)

    # Event: IssueOpened
    related_opened = [issue_id, repo_id]
    if user_id: related_opened.append(user_id)
    related_opened.extend(label_ids)

    builder.add_event("IssueOpened", issue["createdAt"], related_opened)

     # Event: IssueClosed
    if issue["closedAt"]:
        builder.add_event("IssueClosed", issue["closedAt"], [issue_id, repo_id])

    # Handle Pull Request specific data
    if issue.get("type") == "PullRequest" or "merged" in issue:
        pr_id = f"pr_{issue_num}"
        builder.add_object(pr_id, "PullRequest", {
            "number": issue_num,
            "merged": issue.get("merged", False)
        })

        if issue.get("merged") and issue.get("mergedAt"):
            related_merged = [pr_id, issue_id, repo_id]
            if user_id: related_merged.append(user_id)
            builder.add_event("PRMerged", issue["mergedAt"], related_merged)

        # Map Reviews
        if "reviews" in issue:
            for review in issue["reviews"].get("nodes", []):
                if review["state"] != "PENDING":
                    rev_author = review["author"]["login"] if review["author"] else "ghost"
                    rev_user_id = f"user_{rev_author}"
                    builder.add_object(rev_user_id, "User", {"login": rev_author})
                    builder.add_event(
                        "PRReviewSubmitted",
                        review["submittedAt"],
                        [pr_id, repo_id, rev_user_id],
                        {"state": review["state"]}
                    )

def process_workflow_run(run, builder: OCELBuilder, repo_id):
    """Processes GitHub Action runs and connects them to Commits and Branches."""
    run_id = f"workflow_{run['id']}"
    commit_id = f"commit_{run['head_sha']}"

    # Create Objects
    builder.add_object(run_id, "WorkflowRun", {
        "run_id": str(run["id"]),
        "conclusion": run["conclusion"] or "in_progress",
        "name": run["name"]

    })

    if commit_id not in builder.ocel["ocel:objects"]:
        builder.add_object(commit_id, "Commit", {
            "sha": run['head_sha'],
            "source": "workflow_inferred"
        })

    related_objects = [run_id, repo_id, commit_id]

    for pr in run.get("pull_requests", []):
        pr_id = f"pr_{pr['number']}"
        if pr_id not in builder.ocel["ocel:objects"]:
            builder.add_object(pr_id, "PullRequest", {"number": pr['number'], "source": "rest_stub"})
        related_objects.append(pr_id)

    if run.get("run_started_at"):
        builder.add_event("WorkflowRunStarted", run["run_started_at"], related_objects)

    start = parse_time(run.get("run_started_at"))
    end = parse_time(run.get("updated_at"))
    duration = (end - start).total_seconds() if start and end else 0

    builder.add_event(
        "WorkflowRunCompleted",
        run["updated_at"],
        related_objects,
        {"conclusion": run["conclusion"], "duration_seconds": duration}
    )


def process_commit_rest(commit, builder: OCELBuilder, repo_id):
    """Processes detailed Commits including file-level granularity."""
    sha = commit["sha"]
    commit_id = f"commit_{sha}"
    author_login = commit["author"]["login"] if commit["author"] else "unknown"
    user_id = f"user_{author_login}"

    builder.add_object(commit_id, "Commit", {"sha": sha, "message": commit["commit"]["message"]})
    builder.add_object(user_id, "User", {"login": author_login})

    related_objects = [commit_id, repo_id, user_id]

    files_touched = 0
    # Map File Objects
    for file in commit.get("files", []):
        file_path = file["filename"]
        file_id = f"file_{file_path}"
        builder.add_object(file_id, "File", {"path": file_path})
        related_objects.append(file_id)
        files_touched += 1

    stats = commit.get("stats", {})
    builder.add_event(
        "CommitCreated",
        commit["commit"]["author"]["date"],
        related_objects,
        {
            "additions": stats.get("additions", 0),
            "deletions": stats.get("deletions", 0),
            "files_changed": files_touched
        }
    )
