from transform.builder import OCELBuilder

def process_issue_node(issue, builder: OCELBuilder, repo_id):
    issue_num = issue["number"]
    issue_id = f"issue_{issue_num}"

    # Issue Object
    builder.add_object(issue_id, "Issue", {
        "number": issue_num,
        "state": issue["state"],
        "title": issue["title"]
    })

    # User Object
    user_id = None
    if issue.get("author"):
        user_login = issue["author"]["login"]
        user_id = f"user_{user_login}"
        builder.add_object(user_id, "User", {"login": user_login})

    # Event: IssueOpened
    related = [issue_id, repo_id]
    if user_id: related.append(user_id)
    builder.add_event("IssueOpened", issue["createdAt"], related)

    # Special logic for Pull Requests
    if issue.get("type") == "PullRequest":
        pr_id = f"pr_{issue_num}"
        builder.add_object(pr_id, "PullRequest", {"number": issue_num})

        if issue.get("mergedAt"):
            builder.add_event("PRMerged", issue["mergedAt"], [pr_id, issue_id, repo_id])


def process_workflow_run(run, builder: OCELBuilder, repo_id):

    run_id = f"workflow_{run['id']}"
    commit_id = f"commit_{run['head_sha']}"
    branch_id = f"branch_{run['head_branch']}"

    # Objets
    builder.add_object(run_id, "WorkflowRun", {
        "run_id": str(run["id"]),
        "conclusion": run["conclusion"] or "in_progress",
        "name": run["name"]
        }
    )

    builder.add_object(commit_id, "Commit", {"sha": run["head_sha"]})

    if run["head_branch"]:
        builder.add_object(branch_id, "Branch", {"name": run["head_branch"]})
        related_objects = [run_id, repo_id, commit_id]
        if run["head_branch"]:
            related_objects.append(branch_id)
    builder.add_event(
        "WorkflowRunCompleted",
        run["updated_at"],
        related_objects,
        {"conclusion": run["conclusion"]}
    )
    
    