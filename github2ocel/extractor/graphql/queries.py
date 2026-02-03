
ISSUES_QUERY = """
query($owner: String!, $repo: String!, $cursor: String, $pageSize: Int!) {
  repository(owner: $owner, name: $repo) {
    issues(
      first: $pageSize,
      after: $cursor,
      orderBy: {field: CREATED_AT, direction: ASC}
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        title
        state
        createdAt
        closedAt
        author { login }
        assignees(first: 5) {
          nodes { login }
        }
        labels(first: 10) {
          nodes { name color }
        }
        comments(first: 10) {
          nodes {
            createdAt
            lastEditedAt
            body
            author { login }
          }
        }
        timelineItems(
          first: 50,
          itemTypes: [ASSIGNED_EVENT, UNASSIGNED_EVENT]
        ) {
          nodes {
            __typename
            ... on AssignedEvent {
              createdAt
              assignee { ... on User { login } }
            }
            ... on UnassignedEvent {
              createdAt
              assignee { ... on User { login } }
            }
          }
        }
      }
    }
  }
}
"""

PRS_QUERY = """
query($owner: String!, $repo: String!, $cursor: String, $pageSize: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequests(
      first: $pageSize,
      after: $cursor,
      orderBy: {field: CREATED_AT, direction: ASC}
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        title
        state
        createdAt
        closedAt
        merged
        mergedAt
        author { login }
        assignees(first: 5) {
          nodes { login }
        }
        labels(first: 10) {
          nodes { name color }
        }
        reviewRequests(first: 5) {
          nodes {
            requestedReviewer {
              ... on User { login }
            }
          }
        }
        reviews(first: 10) {
          nodes {
            state
            submittedAt
            author { login }
            comments(first: 10) {
              nodes {
                id
                body
                createdAt
                author { login }
              }
            }
          }
        }
        reviewThreads(first: 20) {
          nodes {
            id
            isResolved
            resolvedBy { login }
            comments(first: 50) {
              nodes {
                id
                body
                createdAt
                author { login }
              }
            }
          }
        }
        statusCheckRollup {
          contexts(first: 50) {
            nodes {
              ... on CheckRun {
                __typename
                id
                name
                status
                conclusion
                startedAt
                completedAt
                detailsUrl
              }
            }
          }
        }
        milestone {
          id
          title
          state
          dueOn
        }
        timelineItems(
          first: 50,
          itemTypes: [
            ASSIGNED_EVENT,
            UNASSIGNED_EVENT,
            REVIEW_REQUESTED_EVENT,
            REVIEW_REQUEST_REMOVED_EVENT
          ]
        ) {
          nodes {
            __typename
            ... on AssignedEvent {
              createdAt
              assignee { ... on User { login } }
            }
            ... on UnassignedEvent {
              createdAt
              assignee { ... on User { login } }
            }
            ... on ReviewRequestedEvent {
              createdAt
              requestedReviewer { ... on User { login } }
            }
            ... on ReviewRequestRemovedEvent {
              createdAt
              requestedReviewer { ... on User { login } }
            }
          }
        }
      }
    }
  }
}
"""