REPO_STATS_QUERY = """
query GetRepoStats($owner: String!, $repo: String!, $since: DateTime, $sinceGit: GitTimestamp) {
  repository(owner: $owner, name: $repo) {
    issues(states: [OPEN, CLOSED], filterBy: { since: $since })  { totalCount }
    allIssues: issues(states: [OPEN, CLOSED])                    { totalCount }
    pullRequests(states: [OPEN, CLOSED, MERGED])                 { totalCount }
    discussions                                                   { totalCount }
    releases                                                      { totalCount }
    milestones(states: [OPEN, CLOSED])                           { totalCount }
    refs(refPrefix: "refs/tags/")                                { totalCount }
    refs2: refs(refPrefix: "refs/heads/")                        { totalCount }

    defaultBranchRef {
      target {
        ... on Commit {
          history(since: $sinceGit) { totalCount }
          allHistory: history      { totalCount }
        }
      }
    }
  }
  rateLimit { cost remaining resetAt }
}
"""

ISSUES_QUERY = """
query GetIssues(
  $owner: String!
  $repo:  String!
  $cursor: String
  $pageSize: Int!
  $since: DateTime
) {
  repository(owner: $owner, name: $repo) {
    issues(
      first: $pageSize
      after: $cursor
      states: [OPEN, CLOSED]
      orderBy: { field: CREATED_AT, direction: ASC }
      filterBy: { since: $since }
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        __typename
        id
        number
        title
        url
        state
        stateReason
        createdAt
        updatedAt
        closedAt

        # Metrics
        reactions(first: 1) { totalCount }
        participants(first: 0) { totalCount }

        body
        bodyText

        author {
          login
          __typename
          ... on User { id }
          ... on Bot  { id }
        }

        # Relationships -> O2O
        assignees(first: 10) {
          nodes { login id }
        }

        labels(first: 20) {
          nodes { id name color }
        }

        milestone {
          id
          number
          title
          state
          dueOn
          createdAt
          closedAt
          progressPercentage
          creator { login }
        }

        # Comments (events: IssueCommentCreated)
        comments(first: 50) {
          pageInfo { hasNextPage endCursor }
          totalCount
          nodes {
            id
            createdAt
            lastEditedAt
            body
            author { login }
            reactions(first: 1) { totalCount }
          }
        }
      }
    }
  }

  rateLimit { cost remaining resetAt }
}
"""

PULL_REQUESTS_QUERY = """
query GetPullRequests(
  $owner: String!
  $repo:  String!
  $cursor: String
  $pageSize: Int!
) {
  repository(owner: $owner, name: $repo) {
    pullRequests(
      first: $pageSize
      after: $cursor
      states: [OPEN, CLOSED, MERGED]
      orderBy: { field: UPDATED_AT, direction: ASC }
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        __typename
        id
        number
        title
        url

        # Lifecycle
        state
        isDraft
        createdAt
        updatedAt
        closedAt
        merged
        mergedAt
        mergedBy { login }
        reviewDecision

        # Branch information (-> O2O Branch objects)
        headRefName
        headRefOid
        baseRefName
        headRepository { nameWithOwner isPrivate }
        baseRepository { nameWithOwner }

        # Code metrics
        additions
        deletions
        changedFiles

        # Social
        body
        bodyText
        author {
          login
          __typename
          ... on User { id }
          ... on Bot  { id }
        }
        assignees(first: 10) {
          nodes { login id }
        }
        participants(first: 0) { totalCount }
        reactions(first: 1) { totalCount }

        labels(first: 20) {
          nodes { id name color }
        }

        milestone {
          id
          number
          title
          state
          dueOn
          createdAt
          closedAt
          progressPercentage
          creator { login }
        }

        # Lightweight commit list for PR -> Commit linking only
        # Full commit data comes from COMMITS_QUERY
        commits(first: 100) {
          totalCount
          nodes {
            commit {
              oid
              committedDate
              author { user { login } }
            }
          }
        }

        # Comments (events: PRCommentCreated)
        comments(first: 50) {
          pageInfo { hasNextPage endCursor }
          totalCount
          nodes {
            id
            createdAt
            lastEditedAt
            bodyText
            author { login }
          }
        }

        # CI status on the PR head (cheap, single field)
        statusCheckRollup {
          state
          contexts(first: 30) {
            nodes {
              __typename
              ... on CheckRun {
                id
                name
                status
                conclusion
                startedAt
                completedAt
                detailsUrl
                checkSuite {
                  workflowRun {
                    databaseId
                  }
                }
              }
              ... on StatusContext {
                context
                state
                createdAt
                targetUrl
              }
            }
          }
        }
      }
    }
  }

  rateLimit { cost remaining resetAt }
}
"""

TAGS_QUERY = """
query GetTags(
  $owner: String!
  $repo:  String!
  $pageSize: Int!
  $cursor: String
) {
  repository(owner: $owner, name: $repo) {
    refs(
      refPrefix: "refs/tags/"
      first: $pageSize
      after: $cursor
      orderBy: { field: TAG_COMMIT_DATE, direction: DESC }
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        target {
          __typename
          # Lightweight tag -> points directly to a commit
          ... on Commit {
            oid
            committedDate
            author { user { login id } }
          }
          # Annotated tag -> has its own object with tagger info
          ... on Tag {
            oid
            message
            tagger {
              date
              user { login id }
            }
            target {
              ... on Commit {
                oid
                committedDate
              }
            }
          }
        }
      }
    }
  }

  rateLimit { cost remaining resetAt }
}
"""

MILESTONES_QUERY = """
query GetMilestones(
  $owner: String!
  $repo:  String!
  $pageSize: Int!
  $cursor: String
) {
  repository(owner: $owner, name: $repo) {
    milestones(
      first: $pageSize
      after: $cursor
      states: [OPEN, CLOSED]
      orderBy: { field: CREATED_AT, direction: ASC }
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        number
        title
        description
        state
        dueOn
        createdAt
        updatedAt
        closedAt
        progressPercentage

        creator { login }

        # Issue/PR counts give derived metrics for the Milestone object
        issues(states: [OPEN])   { totalCount }
        closedIssues: issues(states: [CLOSED]) { totalCount }
        pullRequests(states: [OPEN])   { totalCount }
        mergedPRs: pullRequests(states: [MERGED]) { totalCount }
      }
    }
  }

  rateLimit { cost remaining resetAt }
}
"""

ISSUE_COMMENTS_QUERY = """
query GetIssueComments(
  $owner:       String!
  $repo:        String!
  $issueNumber: Int!
  $cursor:      String
  $pageSize:    Int!
) {
  repository(owner: $owner, name: $repo) {
    issue(number: $issueNumber) {
      number
      comments(first: $pageSize, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        totalCount
        nodes {
          id
          createdAt
          lastEditedAt
          bodyText
          body
          author { login }
          reactions(first: 1) { totalCount }
        }
      }
    }
  }
  rateLimit { cost remaining resetAt }
}
"""


PR_COMMENTS_QUERY = """
query GetPRComments(
  $owner:    String!
  $repo:     String!
  $prNumber: Int!
  $cursor:   String
  $pageSize: Int!
) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $prNumber) {
      number
      comments(first: $pageSize, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        totalCount
        nodes {
          id
          createdAt
          lastEditedAt
          bodyText
          body
          author { login }
          reactions(first: 1) { totalCount }
        }
      }
    }
  }
  rateLimit { cost remaining resetAt }
}
"""


PR_COMMITS_QUERY = """
query GetPRCommits(
  $owner:    String!
  $repo:     String!
  $prNumber: Int!
  $cursor:   String
  $pageSize: Int!
) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $prNumber) {
      number
      commits(first: $pageSize, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        totalCount
        nodes {
          commit {
            oid
            committedDate
            author { user { login } }
          }
        }
      }
    }
  }
  rateLimit { cost remaining resetAt }
}
"""


PR_REVIEWS_QUERY = """
query GetPRReviews(
  $owner: String!
  $repo:  String!
  $prNumber: Int!
  $cursor: String
  $pageSize: Int!
) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $prNumber) {
      id
      number

      reviews(first: $pageSize, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        totalCount
        nodes {
          id
          state          # APPROVED | CHANGES_REQUESTED | COMMENTED | DISMISSED | PENDING
          submittedAt
          body
          author {
            login
            __typename
            ... on User { id }
          }

          # Inline code comments within this review (ReviewComment objects)
          comments(first: 50) {
            pageInfo { hasNextPage endCursor }
            totalCount
            nodes {
              id
              createdAt
              updatedAt: lastEditedAt
              body
              path
              line
              position
              diffHunk
              author { login }
              reactions(first: 1) { totalCount }
            }
          }
        }
      }
      # Review threads (resolved/unresolved — separate from reviews)
      reviewThreads(first: 50) {
        pageInfo { hasNextPage endCursor }
        totalCount
        nodes {
          id
          isResolved
          isOutdated
          resolvedBy { login }
          comments(first: 10) {
            nodes {
              id
              createdAt
              body
              path
              author { login }
            }
          }
        }
      }
    }
  }

  rateLimit { cost remaining resetAt }
}
"""

PR_TIMELINE_QUERY = """
query GetTimeline(
  $owner: String!
  $repo:  String!
  $prNumber: Int!
  $cursor: String
  $pageSize: Int!
) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $prNumber) {
      id
      number
      timelineItems(
        first: $pageSize
        after: $cursor
        itemTypes: [
          ASSIGNED_EVENT
          UNASSIGNED_EVENT
          REVIEW_REQUESTED_EVENT
          REVIEW_REQUEST_REMOVED_EVENT
          READY_FOR_REVIEW_EVENT
          CONVERT_TO_DRAFT_EVENT
          LABELED_EVENT
          UNLABELED_EVENT
          MILESTONED_EVENT
          DEMILESTONED_EVENT
          CLOSED_EVENT
          REOPENED_EVENT
          MERGED_EVENT
          HEAD_REF_FORCE_PUSHED_EVENT
          DEPLOYED_EVENT
          CROSS_REFERENCED_EVENT
          CONNECTED_EVENT
          DISCONNECTED_EVENT
        ]
      ) {
        pageInfo { hasNextPage endCursor }
        nodes {
          __typename

          ... on AssignedEvent {
            createdAt
            actor { login ... on User { id } }
            assignee { ... on User { login id } }
          }

          ... on UnassignedEvent {
            createdAt
            actor { login ... on User { id } }
            assignee { ... on User { login id } }
          }

          ... on ReviewRequestedEvent {
            createdAt
            actor { login }
            requestedReviewer {
              __typename
              ... on User { login id }
              ... on Team { name id }
            }
          }

          ... on ReviewRequestRemovedEvent {
            createdAt
            actor { login }
            requestedReviewer {
              __typename
              ... on User { login id }
              ... on Team { name id }
            }
          }

          ... on ReadyForReviewEvent {
            createdAt
            actor { login }
          }

          ... on ConvertToDraftEvent {
            createdAt
            actor { login }
          }

          ... on LabeledEvent {
            createdAt
            actor { login }
            label { id name color }
          }

          ... on UnlabeledEvent {
            createdAt
            actor { login }
            label { id name color }
          }

          ... on MilestonedEvent {
            createdAt
            actor { login }
            milestoneTitle
          }

          ... on DemilestonedEvent {
            createdAt
            actor { login }
            milestoneTitle
          }

          ... on ClosedEvent {
            createdAt
            actor { login ... on User { id } }
            closer {
              __typename
              ... on PullRequest { id number }
              ... on Commit { oid }
            }
          }

          ... on ReopenedEvent {
            createdAt
            actor { login }
          }

          ... on MergedEvent {
            createdAt
            actor { login }
            mergeRefName
            commit { oid }
          }

          ... on HeadRefForcePushedEvent {
            createdAt
            actor { login }
            beforeCommit { oid }
            afterCommit { oid }
          }

          ... on DeployedEvent {
            createdAt
            actor { login }
            deployment {
              databaseId
              state
              environment
              creator { login }
            }
          }

          ... on CrossReferencedEvent {
            createdAt
            actor { login }
            source {
              __typename
              ... on PullRequest { id number }
              ... on Issue { id number }
            }
          }

          ... on ConnectedEvent {
            createdAt
            actor { login }
            subject {
              __typename
              ... on Issue { id number }
              ... on PullRequest { id number }
            }
          }

          ... on DisconnectedEvent {
            createdAt
            actor { login }
            subject {
              __typename
              ... on Issue { id number }
              ... on PullRequest { id number }
            }
          }
        }
      }
    }
  }

  rateLimit { cost remaining resetAt }
}
"""

ISSUE_TIMELINE_QUERY = """
query GetIssueTimeline(
  $owner: String!
  $repo:  String!
  $issueNumber: Int!
  $cursor: String
  $pageSize: Int!
) {
  repository(owner: $owner, name: $repo) {
    issue(number: $issueNumber) {
      id
      number
      timelineItems(
        first: $pageSize
        after: $cursor
        itemTypes: [
          ASSIGNED_EVENT
          UNASSIGNED_EVENT
          LABELED_EVENT
          UNLABELED_EVENT
          MILESTONED_EVENT
          DEMILESTONED_EVENT
          CLOSED_EVENT
          REOPENED_EVENT
          CROSS_REFERENCED_EVENT
          CONNECTED_EVENT
          DISCONNECTED_EVENT
        ]
      ) {
        pageInfo { hasNextPage endCursor }
        nodes {
          __typename

          ... on AssignedEvent {
            createdAt
            actor { login ... on User { id } }
            assignee { ... on User { login id } }
          }

          ... on UnassignedEvent {
            createdAt
            actor { login ... on User { id } }
            assignee { ... on User { login id } }
          }

          ... on LabeledEvent {
            createdAt
            actor { login }
            label { id name color }
          }

          ... on UnlabeledEvent {
            createdAt
            actor { login }
            label { id name color }
          }

          ... on MilestonedEvent {
            createdAt
            actor { login }
            milestoneTitle
          }

          ... on DemilestonedEvent {
            createdAt
            actor { login }
            milestoneTitle
          }

          ... on ClosedEvent {
            createdAt
            actor { login ... on User { id } }
            closer {
              __typename
              ... on PullRequest { id number }
              ... on Commit { oid }
            }
          }

          ... on ReopenedEvent {
            createdAt
            actor { login }
          }

          ... on CrossReferencedEvent {
            createdAt
            actor { login }
            source {
              __typename
              ... on PullRequest { id number }
              ... on Issue { id number }
            }
          }

          ... on ConnectedEvent {
            createdAt
            actor { login }
            subject {
              __typename
              ... on Issue { id number }
              ... on PullRequest { id number }
            }
          }

          ... on DisconnectedEvent {
            createdAt
            actor { login }
            subject {
              __typename
              ... on Issue { id number }
            }
          }
        }
      }
    }
  }

  rateLimit { cost remaining resetAt }
}
"""


COMMITS_QUERY = """
query GetCommits(
  $owner: String!
  $repo:  String!
  $pageSize: Int!
  $cursor: String
  $since: GitTimestamp
) {
  repository(owner: $owner, name: $repo) {
    defaultBranchRef {
      name
      target {
        ... on Commit {
          history(first: $pageSize, after: $cursor, since: $since) {
            pageInfo { hasNextPage endCursor }
            nodes {
              oid
              message
              committedDate
              authoredDate

              # Code diff metrics (counts only — paths not available in GraphQL)
              additions
              deletions
              changedFilesIfAvailable

              # Author / committer
              author {
                name
                email
                date
                user { login id }
              }
              committer {
                name
                date
                user { login id }
              }

              # Signature
              signature {
                isValid
                signer { login }
              }

              # Merge detection
              parents(first: 3) {
                totalCount
                nodes { oid }
              }

              # PR association (→ Commit–PR O2O)
              associatedPullRequests(first: 5) {
                nodes {
                  number
                  id
                }
              }

              # CI checks on this commit
              checkSuites(first: 3) {
                nodes {
                  conclusion
                  status
                  workflowRun {
                    databaseId
                    event
                    workflow { name }
                  }
                  checkRuns(first: 10) {
                    nodes {
                      id
                      name
                      status
                      conclusion
                      startedAt
                      completedAt
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }

  rateLimit { cost remaining resetAt }
}
"""


DEPLOYMENTS_QUERY = """
query GetDeployments(
  $owner: String!
  $repo:  String!
  $pageSize: Int!
  $cursor: String
) {
  repository(owner: $owner, name: $repo) {
    deployments(
      first: $pageSize
      after: $cursor
      orderBy: { field: CREATED_AT, direction: DESC }
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        databaseId
        environment
        state
        description
        task
        createdAt
        updatedAt

        # Commit deployed (-> O2O Commit)
        commit { oid committedDate }

        # Branch/ref (-> O2O Branch)
        ref { name }

        creator {
          login
          __typename
          ... on User { id }
          ... on Bot  { id }
        }

        # Full status history (events: DeploymentCreated, Succeeded, Failed)
        statuses(first: 10) {
          nodes {
            state        # PENDING | SUCCESS | FAILURE | ERROR | INACTIVE | IN_PROGRESS | QUEUED | WAITING
            description
            logUrl
            environmentUrl
            createdAt
            creator {
              login
              ... on User { id }
            }
          }
        }
      }
    }
  }

  rateLimit { cost remaining resetAt }
}
"""

WORKFLOW_RUN_FIELDS = [
    "id",               # run_id
    "name",             # workflow name
    "display_title",
    "event",            # push | pull_request | schedule | workflow_dispatch …
    "status",           # queued | in_progress | completed
    "conclusion",       # success | failure | cancelled | skipped | timed_out | action_required
    "workflow_id",
    "run_number",
    "run_attempt",
    "head_branch",
    "head_sha",
    "head_commit",      # message, author, timestamp
    "created_at",
    "updated_at",
    "run_started_at",
    "triggering_actor", # login
    "actor",            # login (who triggered)
    "repository",       # nameWithOwner
    "html_url",
]

# Fields extracted per WorkflowJob:
WORKFLOW_JOB_FIELDS = [
    "id",
    "run_id",
    "name",
    "status",
    "conclusion",
    "started_at",
    "completed_at",
    "runner_name",
    "runner_group_name",
    "steps",            # list: name, status, conclusion, number, started_at, completed_at
    "html_url",
]

"""Releases GraphQL query."""

RELEASES_QUERY = """
query GetReleases(
  $owner: String!
  $repo:  String!
  $pageSize: Int!
  $cursor: String
) {
  repository(owner: $owner, name: $repo) {
    releases(
      first: $pageSize
      after: $cursor
      orderBy: { field: CREATED_AT, direction: ASC }
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        name
        tagName
        description
        createdAt
        publishedAt
        isPrerelease
        isDraft

        author { login }

        # Commit the tag points to (-> O2O Commit)
        tag {
          target {
            __typename
            ... on Commit {
              oid
              committedDate
              author { user { login } }
            }
            ... on Tag {
              oid
              tagger { date user { login } }
              target {
                ... on Commit { oid }
              }
            }
          }
        }

        releaseAssets(first: 10) {
          totalCount
          nodes {
            name
            downloadCount
            size
            contentType
          }
        }
      }
    }
  }

  rateLimit { cost remaining resetAt }
}
"""

"""Tags GraphQL query — handles both lightweight and annotated tags."""


DISCUSSIONS_QUERY = """
query GetDiscussions(
  $owner: String!
  $repo:  String!
  $pageSize: Int!
  $cursor: String
) {
  repository(owner: $owner, name: $repo) {
    discussions(
      first: $pageSize
      after: $cursor
      orderBy: { field: CREATED_AT, direction: ASC }
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        __typename
        id
        number
        title
        url
        createdAt
        updatedAt
        answerChosenAt
        locked
        upvoteCount
        body
        bodyText

        answerChosenBy { login }

        author {
          login
          __typename
          ... on User { id }
          ... on Bot  { id }
        }

        category { id name }

        labels(first: 10) {
          nodes { id name color }
        }

        reactions(first: 1) { totalCount }

        comments(first: 50) {
          pageInfo { hasNextPage endCursor }
          totalCount
          nodes {
            id
            createdAt
            updatedAt
            body
            bodyText
            isAnswer
            author { login }
            reactions(first: 1) { totalCount }
            replies(first: 10) {
              pageInfo { hasNextPage endCursor }
              totalCount
              nodes {
                id
                body
                createdAt
                author { login }
              }
            }
          }
        }
      }
    }
  }

  rateLimit { cost remaining resetAt }
}
"""