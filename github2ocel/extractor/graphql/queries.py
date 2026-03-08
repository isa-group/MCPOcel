REPO_STATS_QUERY = """
query GetRepoStats($owner: String!, $repo: String!) {
  repository(owner: $owner, name: $repo) {
    issues(states: [OPEN, CLOSED])         { totalCount }
    pullRequests(states: [OPEN, CLOSED, MERGED]) { totalCount }
    discussions                             { totalCount }
    releases                               { totalCount }
    milestones(states: [OPEN, CLOSED])     { totalCount }
    refs(refPrefix: "refs/tags/")          { totalCount }
    refs2: refs(refPrefix: "refs/heads/")  { totalCount }

    defaultBranchRef {
      target {
        ... on Commit {
          history { totalCount }
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
      orderBy: { field: CREATED_AT, direction: ASC }
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
