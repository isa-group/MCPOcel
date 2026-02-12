# Constants for Activity Names
class Activities:
    """Registry of all Activity names used in the log."""
    ISSUE_OPENED = "IssueOpened"
    ISSUE_CLOSED = "IssueClosed"
    ISSUE_COMMENT = "IssueCommentCreated"
    ISSUE_ASSIGNED = "IssueAssigned"
    ISSUE_UNASSIGNED = "IssueUnassigned"

    PR_OPENED = "PROpened"
    PR_MERGED = "PRMerged"
    PR_CLOSED = "PRClosed"
    PR_REVIEW = "PRReviewSubmitted"
    PR_COMMENT = "PRCommented"
    PR_REVIEW_APPROVED = "PRReviewApproved"
    PR_REVIEW_CHANGES_REQUESTED = "PRReviewChangesRequested"
    PR_REVIEW_COMMENTED = "PRReviewCommented"
    PR_REVIEW_DISMISSED = "PRReviewDismissed"
    PR_ASSIGNED = "PRAssigned"
    PR_UNASSIGNED = "PRUnassigned"
    PR_REVIEW_REQUESTED = "PRReviewRequested"
    PR_REVIEW_REQUEST_REMOVED = "PRReviewRequestRemoved"

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

    REVIEW_COMMENT_CREATED = "ReviewCommentCreated"
    REVIEW_COMMENT_EDITED = "ReviewCommentEdited"
    REVIEW_COMMENT_DELETED = "ReviewCommentDeleted"

    DEPLOYMENT_CREATED = "DeploymentCreated"
    DEPLOYMENT_SUCCEEDED = "DeploymentSucceeded"
    DEPLOYMENT_FAILED = "DeploymentFailed"
    DEPLOYMENT_ERROR = "DeploymentError"

    THREAD_RESOLVED = "ReviewThreadResolved"
    MILESTONE_ASSIGNED = "MilestoneAssigned"
    JOB_STARTED = "WorkflowJobStarted"
    JOB_COMPLETED = "WorkflowJobCompleted"

    BRANCH_CREATED = "BranchCreated"
    BRANCH_MERGED = "BranchMerged"
    BRANCH_DELETED = "BranchDeleted"
    BRANCH_OBSERVED = "BranchSnapshot"