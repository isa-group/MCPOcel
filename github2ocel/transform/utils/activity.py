# Constants for Activity Names
class Activities:
    """Registry of all Activity names used in the log."""
    ISSUE_OPENED = "IssueOpened"
    ISSUE_CLOSED = "IssueClosed"
    ISSUE_ASSIGNED = "IssueAssigned"
    ISSUE_UNASSIGNED = "IssueUnassigned"
    ISSUE_REOPENED='IssueReopened'
    ISSUE_LINKED = "IssueLinked"
    ISSUE_UNLINKED = "IssueUnlinked"

    CROSS_REFERENCED = 'CrossReferenced'

    PR_OPENED = "PROpened"
    PR_MERGED = "PRMerged"
    PR_CLOSED = "PRClosed"
    PR_ASSIGNED = "PRAssigned"
    PR_UNASSIGNED = "PRUnassigned"
    PR_REOPENED = "PRReopened"
    PR_FORCE_PUSHED='PRForcePushed'
    PR_CI_STATE = "PRCIState"
    PR_CONVERT_DRAFT = "PRConvertedToDraft"
    PR_FOR_REVIEW = "PRReadyForReview"

    PR_REVIEW_APPROVED = "PRReviewApproved"
    PR_REVIEW_COMMENTED = "PRReviewCommented"
    PR_REVIEW_DISMISSED = "PRReviewDismissed"
    PR_REVIEW_REQUESTED = "PRReviewRequested"
    PR_REVIEW_CHANGES_REQUESTED = "PRReviewChangesRequested"
    PR_REVIEW_REQUEST_REMOVED = "PRReviewRequestRemoved"

    # Comments
    COMMENT_CREATED = "CommentCreated"
    COMMENT_EDITED = "CommentEdited"

    # Labels
    LABEL_ADDED = "LabelAdded"
    LABEL_REMOVED = "LabelRemoved"

    # Dev & DevOps
    COMMIT_CREATED = "CommitCreated"
    RELEASE_CREATED = "ReleaseCreated"
    RELEASE_PUBLISHED = "ReleasePublished"

    DEPLOYMENT_CREATED = "DeploymentCreated"
    DEPLOYMENT_SUCCEEDED = "DeploymentSucceeded"
    DEPLOYMENT_FAILED = "DeploymentFailed"
    DEPLOYMENT_ERROR = "DeploymentError"

    THREAD_RESOLVED = "ReviewThreadResolved"

    MILESTONE_CREATED = "MilestoneCreated"
    MILESTONE_ASSIGNED = "MilestoneAssigned"
    MILESTONE_CLOSED = "MilestoneClosed"
    MILESTONE_UPDATED = "MilestoneUpdated"
    MILESTONE_REMOVED = "MilestoneRemoved"

    JOB_STARTED = "WorkflowJobStarted"
    JOB_COMPLETED = "WorkflowJobCompleted"
    WORKFLOW_STARTED = "WorkflowRunStarted"
    WORKFLOW_COMPLETED = "WorkflowRunCompleted"

    BRANCH_CREATED = "BranchCreated" # GitHub not provide a `createdAt` field for branches
    BRANCH_MERGED = "BranchMerged"
    BRANCH_DELETED = "BranchDeleted"
    BRANCH_RESTORED = "BranchRestored"
    BRANCH_OBSERVED = "BranchSnapshot"

    TAG_CREATED = "TagCreated"

    # Discussions
    DISCUSSION_CREATED = "DiscussionCreated"
    DISCUSSION_ANSWERED = "DiscussionAnswered"
