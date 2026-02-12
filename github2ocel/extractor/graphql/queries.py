ISSUES_QUERY = """
query GetIssues($owner: String!, $repo: String!, $cursor: String, $pageSize: Int!) {
  repository(owner: $owner, name: $repo) {
    issues(
      first: $pageSize
      after: $cursor
      orderBy: {field: CREATED_AT, direction: ASC}
    ) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        # --- IDENTIDAD & TRAZABILIDAD (NUEVO) ---
        id                # Global Node ID (estable)
        number            # ID humano (#42)
        title
        url               # Link directo

        # --- ESTADO & CICLO DE VIDA ---
        state
        stateReason       # COMPLETED, NOT_PLANNED
        createdAt
        closedAt
        updatedAt         # Vital para delta loads

        # --- PLANIFICACIÓN (NUEVO) ---
        milestone {
          id
          title
          state
          dueOn
        }

        # --- CONTENIDO (TEXT MINING) ---
        body              # Markdown
        bodyText          # Texto plano

        # --- PARTICIPACIÓN SOCIAL ---
        author { login }

        # Ownership
        assignees(first: 5) {
          nodes { login }
        }

        # Popularidad / Calor
        reactions(first: 1) { totalCount }
        participants(first: 0) { totalCount } # (NUEVO) Solo el contador, muy barato

        labels(first: 10) {
          nodes { name color }
        }

        # --- DISCUSIÓN ---
        # Traemos 10 para contexto, y totalCount para métricas
        comments(first: 10) {
          totalCount      # (NUEVO) Para saber si hay 100 comentarios ocultos
          nodes {
            createdAt
            lastEditedAt
            body
            author { login }
            reactions(first: 1) { totalCount }
          }
        }

        # --- EVENTOS DEL PROCESO ---
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
            MILESTONED_EVENT # (NUEVO) Ya que traemos milestones
            DEMILESTONED_EVENT # (NUEVO)
          ]
        ) {
          nodes {
            __typename
            ... on AssignedEvent { createdAt assignee { ... on User { login } } }
            ... on UnassignedEvent { createdAt assignee { ... on User { login } } }
            ... on LabeledEvent { createdAt label { name } }
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

  # Variables de Control (Perfiles)
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
      orderBy: { field: CREATED_AT, direction: ASC }
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        # --- IDENTIDAD ---
        id
        number
        title
        url

        # --- ESTADO ---
        state
        isDraft
        createdAt
        updatedAt
        closedAt
        merged
        mergedAt

        # --- RAMAS & COMMITS ---
        headRefName
        headRefOid      # SHA del último commit (Vital para enlazar con REST)
        baseRefName

        # --- ESFUERZO (Métricas) ---
        additions
        deletions
        changedFiles
        commits { totalCount } # Solo conteo, el detalle va por REST

        # --- CONTENIDO ---
        body
        bodyText

        # --- PARTICIPACIÓN ---
        author { login }
        assignees(first: 5) { nodes { login } }
        participants(first: 0) { totalCount } # Métricas baratas
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

        # --- REVIEWS (Configurable) ---
        reviews(first: 20) @include(if: $withReviews) {
          totalCount
          nodes {
            state
            submittedAt
            author { login }
            body
            comments(first: 10) @include(if: $withReviewComments) {
              totalCount
              nodes {
                createdAt
                body
                path
                position
                author { login }
              }
            }
          }
        }

        # --- THREADS (Configurable) ---
        reviewThreads(first: 20) @include(if: $withThreads) {
          totalCount
          nodes {
            isResolved
            resolvedBy { login }
            comments(first: 20) {
              nodes {
                createdAt
                body
                author { login }
              }
            }
          }
        }

        # --- CI/CD (Configurable) ---
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

        # --- TIMELINE (Configurable) ---
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
            ... on AssignedEvent { createdAt assignee { ... on User { login } } }
            ... on ReviewRequestedEvent { createdAt requestedReviewer { ... on User { login } ... on Team { name } } }
            ... on MergedEvent { createdAt mergeRefName }
            ... on HeadRefForcePushedEvent { createdAt }
            ... on MilestonedEvent { createdAt milestoneTitle }
          }
        }
      }
    }
  }

  # --- OBSERVABILIDAD ---
  rateLimit {
    cost
    remaining
    resetAt
  }
}
"""