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

    # Comments
    COMMENT_CREATED = "CommentCreated"
    COMMENT_EDITED = "CommentEdited"

    # Labels
    LABEL_ADDED = "LabelAdded"

    # Dev & DevOps
    COMMIT_CREATED = "CommitCreated"
    WORKFLOW_STARTED = "WorkflowRunStarted"
    WORKFLOW_COMPLETED = "WorkflowRunCompleted"
    RELEASE_CREATED = "ReleaseCreated"