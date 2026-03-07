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
