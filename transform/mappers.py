from .builder import OCELBuilder


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
    builder.add_event("IssueOpened", issue["createdAt"], [issue_id, repo_id])

    # Pull Request with Reviews
    if issue.get("type") == "PullRequest" or "merged" in issue:
        pr_id = f"pr_{issue_num}"
        builder.add_object(pr_id, "PullRequest", {"number": issue_num})

        # New in Commit 4: Iterate through Reviews
        if "reviews" in issue:
            for review in issue["reviews"].get("nodes", []):
                # We only log submitted reviews (not pending)
                if review["state"] != "PENDING":
                    rev_author = review["author"]["login"] if review["author"] else "ghost"
                    rev_user_id = f"user_{rev_author}"

                    # Ensure the Reviewer exists as a User object
                    builder.add_object(rev_user_id, "User", {"login": rev_author})

                    # Event: PRReviewSubmitted
                    # Linked to PR, Repository, and the Reviewer
                    builder.add_event(
                        activity="PRReviewSubmitted",
                        timestamp=review["submittedAt"],
                        related_objects=[pr_id, repo_id, rev_user_id],
                        attributes={"state": review["state"]}
                    )

        if issue.get("mergedAt"):
            builder.add_event("PRMerged", issue["mergedAt"], [pr_id, issue_id, repo_id])