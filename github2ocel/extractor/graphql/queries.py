ISSUES_QUERY = """
query GetIssues($owner: String!, $repo: String!, $cursor: String, $pageSize: Int!) {
  repository(owner: $owner, name: $repo) {
    issues(
      first: $pageSize
      after: $cursor
      states: [OPEN, CLOSED],
      orderBy: {field: CREATED_AT, direction: ASC}
    ) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        # --- Identity ---
        id                # Global Node ID
        number
        title
        url

        # --- Lifecycle ---
        state
        stateReason       # COMPLETED, NOT_PLANNED
        createdAt
        closedAt
        updatedAt

        # --- Planification ---
        milestone {
          id
          title
          state
          dueOn
        }

        # --- Textx mining ---
        body              # Markdown
        bodyText          # Texto plano

        # --- Social ---
        author { 
          login
          ... on User { id }
          ... on Organization { id }
          ... on Bot { id }
        }
        # Ownership
        assignees(first: 5) {
          nodes {
            login
            id
          }
        }
        reactions(first: 1) { totalCount }
        participants(first: 0) { totalCount }
        labels(first: 10) {
          nodes {
            id
            name
            color
          }
        }

        # --- Comments ---
        comments(first: 10) {
          totalCount
          nodes {
            id
            createdAt
            lastEditedAt
            body
            author {
              login
              ... on User { id }
              ... on Organization { id }
              ... on Bot { id }
            }
            reactions(first: 1) { totalCount }
          }
        }

        # --- Process Events ---
        timelineItems(
          first: 50
          itemTypes: [
            ASSIGNED_EVENT
            UNASSIGNED_EVENT
            LABELED_EVENT
            UNLABELED_EVENT
            CLOSED_EVENT
            REOPENED_EVENT
            LOCKED_EVENT
            MILESTONED_EVENT
            DEMILESTONED_EVENT
          ]
        ) {
          nodes {
            __typename
            ... on AssignedEvent { createdAt assignee { ... on User { login id } } }
            ... on UnassignedEvent { createdAt assignee { ... on User { login id } } }
            ... on LabeledEvent { createdAt label { id name } }
            ... on ClosedEvent { createdAt }
            ... on ReopenedEvent { createdAt }
            ... on MilestonedEvent { createdAt milestoneTitle }
          }
        }
      }
    }
  }
}
"""

PRS_QUERY = """
query GetPullRequests(
  $owner: String!
  $repo: String!
  $cursor: String
  $pageSize: Int!

  # Control (Profiles)
  $withReviews: Boolean! = true
  $withReviewComments: Boolean! = false
  $withThreads: Boolean! = false
  $withTimeline: Boolean! = true
  $withStatusChecks: Boolean! = true
) {
  repository(owner: $owner, name: $repo) {
    pullRequests(
      first: $pageSize
      after: $cursor
      states: [OPEN, CLOSED, MERGED],
      orderBy: { field: CREATED_AT, direction: ASC }
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        # --- Identity ---
        id
        number
        title
        url

        # --- State ---
        state
        isDraft
        createdAt
        updatedAt
        closedAt
        merged
        mergedAt

        # --- Branches & Commits ---
        headRefName
        headRefOid
        baseRefName

        # --- Metrics ---
        additions
        deletions
        changedFiles
        commits { totalCount }

        # --- Content ---
        body
        bodyText

        # --- Social ---
        author {
          login
          ... on User { id }
          ... on Organization { id }
          ... on Bot { id }
        }
        assignees(first: 5) { nodes { login id } }
        participants(first: 0) { totalCount }
        reactions(first: 1) { totalCount }
        
        labels(first: 10) {
          nodes {
            id
            name
            color
          }
        }

        milestone {
          id
          title
          state
          dueOn
        }

        # --- Reviews ---
        reviews(first: 20) @include(if: $withReviews) {
          totalCount
          nodes {
            id
            state
            submittedAt
            author { 
              login 
              ... on User { id } 
            }
            body
            comments(first: 10) @include(if: $withReviewComments) {
              totalCount
              nodes {
                id
                createdAt
                body
                path
                position
                author { 
                  login 
                  ... on User { id }
                }
              }
            }
          }
        }

        # --- Review Threads ---
        reviewThreads(first: 20) @include(if: $withThreads) {
          totalCount
          nodes {
          id
            isResolved
            resolvedBy { 
              login 
              ... on User { id } 
            }
            comments(first: 20) {
              nodes {
              id
                createdAt
                body
                author { 
                  login 
                  ... on User { id }
                  ... on Organization { id }
                  ... on Bot { id }
                }
              }
            }
          }
        }

        # --- CI/CD ---
        statusCheckRollup @include(if: $withStatusChecks) {
          contexts(first: 50) {
            nodes {
              ... on CheckRun {
                name
                status
                conclusion
                startedAt
                completedAt
              }
            }
          }
        }

        # --- Timeline ---
        timelineItems(
          first: 50
          itemTypes: [
            ASSIGNED_EVENT, UNASSIGNED_EVENT,
            REVIEW_REQUESTED_EVENT, REVIEW_REQUEST_REMOVED_EVENT,
            READY_FOR_REVIEW_EVENT, CONVERT_TO_DRAFT_EVENT,
            MERGED_EVENT, HEAD_REF_FORCE_PUSHED_EVENT,
            MILESTONED_EVENT, DEMILESTONED_EVENT
          ]
        ) @include(if: $withTimeline) {
          nodes {
            __typename
            ... on AssignedEvent {
              createdAt
              assignee {
                ... on User { login id }
              }
            }
            ... on UnassignedEvent {
              createdAt
              assignee {
                ... on User {
                  login
                  id
                }
              }
            }
            ... on ReviewRequestedEvent {
              createdAt
              requestedReviewer {
                __typename
                ... on User { login id } 
                ... on Team { name }
              }
            }
            ... on MergedEvent { createdAt mergeRefName }
            ... on HeadRefForcePushedEvent { createdAt }
            ... on MilestonedEvent { createdAt milestoneTitle }
          }
        }
      }
    }
  }

  rateLimit {
    cost
    remaining
    resetAt
  }
}
"""

DISCUSSIONS_QUERY = """
query GetDiscussions(
  $owner: String!
  $repo: String!
  $cursor: String
  $pageSize: Int!
) {
  repository(owner: $owner, name: $repo) {
    discussions(first: $pageSize, after: $cursor) {
      pageInfo {
        hasNextPage
        endCursor
      }
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

        body
        bodyText

        author {
          login
          ... on User { id }
          ... on Organization { id }
          ... on Bot { id }
        }

        category {
          id
          name
        }

        reactions(first: 1) { totalCount }

        comments(first: 50) {
          totalCount
          nodes {
            id
            createdAt
            updatedAt
            body
            author {
              login
              ... on User { id }
              ... on Organization { id }
              ... on Bot { id }
            }
            reactions(first: 1) { totalCount }
          }
        }
      }
    }
  }
}
"""