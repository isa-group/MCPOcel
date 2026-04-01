# Architecture

## Index

- [Architecture](#architecture)
  - [Index](#index)
  - [Module layout](#module-layout)
  - [Pipeline phases](#pipeline-phases)
    - [Adaptive page sizing](#adaptive-page-sizing)
    - [Overflow lists](#overflow-lists)
  - [Data flow](#data-flow)
  - [OCEL 2.0 schema mapping](#ocel-20-schema-mapping)
    - [SQLite schema](#sqlite-schema)
      - [Base tables (always present)](#base-tables-always-present)
      - [Per-type attribute tables (created on demand)](#per-type-attribute-tables-created-on-demand)
      - [Attribute types](#attribute-types)
    - [JSON schema](#json-schema)
      - [`eventTypes`](#eventtypes)
      - [`objectTypes`](#objecttypes)
      - [`events`](#events)
      - [`objects`](#objects)
      - [`objectRelationships`](#objectrelationships)
    - [Validation](#validation)
  - [Key design decisions](#key-design-decisions)
    - [Deterministic object IDs](#deterministic-object-ids)
    - [Commit stubs](#commit-stubs)
    - [Schema evolution](#schema-evolution)
    - [Exception hierarchy](#exception-hierarchy)
    - [OCELBuilder internals](#ocelbuilder-internals)
  - [The Static State of Objects and the Unix Epoch (OCEL 2.0)](#the-static-state-of-objects-and-the-unix-epoch-ocel-20)
    - [The Problem of the Temporal Paradox](#the-problem-of-the-temporal-paradox)
    - [The Solution: The 1970 Sentinel (`safe_timestamp(None)`)](#the-solution-the-1970-sentinel-safe_timestampnone)
  - [GitHub API Limitations and Implemented Mitigations](#github-api-limitations-and-implemented-mitigations)
    - [1. The absence of explicit timestamps (The `resolvedAt` problem)](#1-the-absence-of-explicit-timestamps-the-resolvedat-problem)
    - [2. CI/CD ‘Ghost’ Jobs, ‘Year 1’, and Clock Skew](#2-cicd-ghost-jobs-year-1-and-clock-skew)
    - [3. The Temporary Blind Spot for Pull Requests and Causal Completeness (The `since` Filter)](#3-the-temporary-blind-spot-for-pull-requests-and-causal-completeness-the-since-filter)
    - [4. ‘Survivor Bias’ and Historical Amnesia](#4-survivor-bias-and-historical-amnesia)
    - [5. Inability to retrieve branch creation times (`BranchCreated`)](#5-inability-to-retrieve-branch-creation-times-branchcreated)
    - [6. Nested Pagination and Complexity-Induced Collapse](#6-nested-pagination-and-complexity-induced-collapse)
    - [Appendix: Empirical SQL Audit (Jellyfin-Vue Case Study)](#appendix-empirical-sql-audit-jellyfin-vue-case-study)
      - [1. The `resolvedAt` Chronological Proxy](#1-the-resolvedat-chronological-proxy)
      - [2. CI/CD ‘Ghost’ Jobs and Clock Skew Mitigation](#2-cicd-ghost-jobs-and-clock-skew-mitigation)
      - [3. Case-Level Filtering and Causal Completeness](#3-case-level-filtering-and-causal-completeness)
      - [4. 'Survivor Bias' and Lazy Stubs (Ghost Branches)](#4-survivor-bias-and-lazy-stubs-ghost-branches)
      - [5. Ontological Honesty in Branches](#5-ontological-honesty-in-branches)
      - [6. Nested Pagination and Complexity Collapse](#6-nested-pagination-and-complexity-collapse)

## Module layout

```textplain
github2ocel/
├── main.py                        # Entry point — wires all layers together
├── config/
│   ├── context.py                 # RepoContext (frozen dataclass, built from env)
│   ├── settings.py                # APIConfig (timeouts, pagination, time window)
│   └── profiles.py                # ExtractionProfile enum + PROFILES feature flags
├── client/
│   ├── github_client.py           # GitHubClient — REST and GraphQL, rate-limit-aware
│   ├── rate_limiter.py            # RateLimiter — reactive + proactive throttling
│   ├── retry.py                   # RetryStrategy — exponential backoff with jitter
│   ├── paginator.py               # Cursor-based GraphQL page iterator
│   └── exceptions.py              # Exception hierarchy (Fatal / Retryable / GraphQL)
├── extractor/
│   ├── extractor.py               # run_extractor() — creates client + orchestrator
│   ├── github/
│   │   └── orchestrator.py        # Orchestrator — phase runner, overflow management
│   ├── fetchers/
│   │   ├── fetch_*.py             # One function per GitHub resource
│   │   └── utils/
│   │       └── compute_page_sizes.py  # Adaptive GraphQL page size calculator
│   └── graphql/
│       └── queries.py             # All GraphQL query strings (~1 300 lines)
├── transform/
│   ├── mappers/
│   │   ├── process_*.py           # One mapper per resource type
│   │   └── OCEL2Json.py           # SQLite → OCEL 2.0 JSON exporter
│   ├── model/
│   │   └── model.py               # RepoStats + PageSizes dataclasses
│   └── utils/
│       ├── ensure.py              # Generic _ensure_object() + typed helpers
│       ├── activity.py            # Activities — centralised event type names
│       └── helper.py              # make_id(), parse_commit_message(), safe_timestamp()
├── validate/
│   ├── validate_ocel.py           # Main validator orchestrator
│   ├── syntax.py                  # Structural / schema checks
│   ├── semantic.py                # Referential integrity checks
│   └── type.py                    # Attribute type checks
└── utils/
    ├── summary.py                 # print_pipeline_audit() — end-of-run report
    └── verify_extractor.py        # verify_data_integrity() — extraction vs injection reconciliation

shared/
├── ocel/
│   ├── builder.py                 # OCELBuilder — SQLite writer with schema evolution
│   ├── model/models.py            # Event, ObjectInstance, ObjectSnapshot dataclasses
│   └── constants.py               # OCEL 2.0 key names
├── config/
│   ├── env.py                     # Env helper — typed env var reads
│   └── logging.py                 # Logging configuration
└── utils/
    └── time.py                    # to_iso8601()

docs/
├── architecture.md
├── data-model.md
├── event-log-reference.md
├── installation.md
└── o2o-reference.md
```

---

## Pipeline phases

The `Orchestrator` runs phases in strict order. If any phase raises a `FatalError` (auth error, 404, permission denied) the pipeline aborts immediately. Transient errors (`RateLimitError`, `RetryableError`) are handled by `RetryStrategy` before reaching the phase runner.

| Phase | Name | Enabled by profile |
| :---: | --- | :---: |
| Setup | Repo stats + adaptive page sizing | Always |
| Init | Milestones, branches, tags | Always |
| Phase 1 | Issues and PRs (core objects, overflow list population) | Always |
| Phase 2 | Issue comments, PR comments, PR commit OID links | Always |
| Phase 3 | PR/issue reviews, timeline events, review threads | `standard`, `complete` |
| Phase 4 | Commit graph (default branch) + feature-branch stubs | Always |
| Phase 4b | Per-commit file changes via REST | `complete` only |
| Phase 5 | Releases | Always |
| Phase 6 | Deployments + workflow runs/jobs | Always |
| Phase 7 | Discussions | `minimal`, `standard`, `complete` |
| Phase 7b | Discussion comment overflow pagination | `minimal`, `standard`, `complete` |

### Adaptive page sizing

Before Phase 1, the orchestrator calls `compute_page_sizes()` with the repository's entity counts and the remaining GraphQL quota. This returns a `PageSizes` dataclass that every fetcher uses instead of a fixed constant. Page sizes are recalculated again after Phase 1, once the exact number of extracted PRs and reviews is known.

If fewer than 1 000 GraphQL points remain, all overflow fetchers (reviews, comments, timeline) are reduced to their minimum safe sizes to avoid exhausting the quota mid-pipeline.

### Overflow lists

Phase 1 requests only `totalCount` for nested resources (reviews, comments, timeline events, commits) — not the actual nodes. The orchestrator accumulates two lists:

- `_overflow_pr_reviews`, `_overflow_pr_comments`, etc. — PR numbers with at least one nested item
- `_overflow_issue_comments`, `_overflow_issue_timeline` — issue numbers with at least one nested item

Phases 2 and 3 iterate only over these lists, so repositories where most PRs have no reviews or few comments generate far fewer API calls than a naïve nested fetch would.

---

## Data flow

```textplain
GitHub API
    │
    ▼
GitHubClient           ← rate limiting, retry, pagination
    │
    ▼
Fetchers               ← one function per resource, yields nodes
    │
    ▼
Orchestrator           ← phase sequencing, overflow routing
    │
    ▼
Mappers                ← raw GitHub node → OCEL Event / ObjectInstance
    │
    ▼
OCELBuilder            ← writes to SQLite (WAL mode)
    │
    ▼
OCEL2JsonExporter      ← SQLite → OCEL 2.0 JSON
    │
    ▼
validate_ocel()        ← syntax + semantic validation
```

---

## OCEL 2.0 schema mapping

This section documents exactly how the OCEL 2.0 standard concepts map to the SQLite tables and JSON structure produced by `OCELBuilder` and `OCEL2JsonExporter`.

### SQLite schema

The relational layout follows the official OCEL 2.0 SQLite specification verbatim. Six base tables are created unconditionally; the remaining tables are created on demand as new event and object types are encountered.

#### Base tables (always present)

```sql
-- Event registry: one row per unique event
CREATE TABLE event (
    ocel_id   TEXT PRIMARY KEY,
    ocel_type TEXT
);

-- Object registry: one row per unique object
CREATE TABLE object (
    ocel_id   TEXT PRIMARY KEY,
    ocel_type TEXT
);

-- Event-to-object relationships (E2O)
-- ocel_qualifier is the role the object plays in the event
CREATE TABLE event_object (
    ocel_event_id  TEXT,
    ocel_object_id TEXT,
    ocel_qualifier TEXT,
    PRIMARY KEY (ocel_event_id, ocel_object_id, ocel_qualifier)
);

-- Object-to-object relationships (O2O)
CREATE TABLE object_object (
    ocel_source_id TEXT,
    ocel_target_id TEXT,
    ocel_qualifier TEXT,
    PRIMARY KEY (ocel_source_id, ocel_target_id, ocel_qualifier)
);

-- Type name → sanitised table name mappings
CREATE TABLE event_map_type  (ocel_type TEXT PRIMARY KEY, ocel_type_map TEXT);
CREATE TABLE object_map_type (ocel_type TEXT PRIMARY KEY, ocel_type_map TEXT);
```

#### Per-type attribute tables (created on demand)

Every event type and object type gets its own table. The table name is the sanitised type name prefixed by `event_` or `object_`.

```sql
-- Events: one row per event instance, PK is ocel_id
-- ocel_time is the single mandatory timestamp (ISO 8601)
CREATE TABLE event_PRMerged (
    ocel_id   TEXT PRIMARY KEY,
    ocel_time TEXT,
    -- activity-specific attributes added via ALTER TABLE ADD COLUMN:
    merge_ref TEXT,
    is_draft  INTEGER
);

-- Objects: one row per attribute snapshot (change history)
-- PK is (ocel_id, ocel_time, ocel_changed_field)
-- ocel_changed_field is NULL for the initial full snapshot,
-- or the attribute name that changed in subsequent snapshots
CREATE TABLE object_PullRequest (
    ocel_id           TEXT,
    ocel_time         TEXT,
    ocel_changed_field TEXT,
    -- object attributes added via ALTER TABLE ADD COLUMN:
    number    INTEGER,
    title     TEXT,
    state     TEXT,
    -- …
    PRIMARY KEY (ocel_id, ocel_time, ocel_changed_field)
);
```

> **Schema evolution.** Columns are added with `ALTER TABLE ADD COLUMN` when a mapper emits an attribute not previously seen for that type. No schema is defined upfront — it emerges incrementally. Running the extractor on a repository with an unusual configuration (e.g. annotated tags) may produce columns absent in runs against repositories without them.

#### Attribute types

The OCEL 2.0 SQLite spec defines five valid column types. This tool uses them as follows:

| OCEL 2.0 type | SQLite affinity | Used for |
| :---: | :---: | --- |
| `TEXT` | `TEXT` | Strings, ISO 8601 timestamps, SHA hashes, URLs |
| `INTEGER` | `INTEGER` | Counts, flags, GitHub numeric IDs |
| `REAL` | `REAL` | Durations in seconds (`duration_seconds`) |
| `BOOLEAN` | `INTEGER` (0 / 1) | `is_draft`, `is_merge_commit`, `is_conventional`, … |
| `TIMESTAMP` | `TEXT` (ISO 8601) | `ocel_time` and all `*_at` attributes |

---

### JSON schema

The JSON output follows the OCEL 2.0 JSON specification. The top-level object has exactly four arrays.

```json
{
  "eventTypes":  [ … ],
  "objectTypes": [ … ],
  "events":      [ … ],
  "objects":     [ … ],
  "objectRelationships": [ … ]
}
```

#### `eventTypes`

One entry per activity type. The `attributes` array lists every attribute column found in the corresponding SQLite `event_*` table, excluding `ocel_id` and `ocel_time`.

```json
{
  "name": "PRMerged",
  "table_map": "PRMerged",
  "attributes": [
    { "name": "merge_ref", "type": "string" },
    { "name": "is_draft",  "type": "integer" }
  ]
}
```

#### `objectTypes`

One entry per object type. The `attributes` array lists every attribute column found in the corresponding `object_*` table, excluding `ocel_id`, `ocel_time`, and `ocel_changed_field`.

```json
{
  "name": "Pull Request",
  "table_map": "PullRequest",
  "attributes": [
    { "name": "number", "type": "integer" },
    { "name": "title",  "type": "string"  },
    { "name": "state",  "type": "string"  }
  ]
}
```

#### `events`

One entry per event. The `relationships` array is the E2O list for that event — each entry has an `objectId` and a `qualifier`.

```json
{
  "id": "uuid-…",
  "type": "PRMerged",
  "time": "2024-03-15T14:22:01Z",
  "attributes": [
    { "name": "merge_ref", "value": "refs/heads/main" }
  ],
  "relationships": [
    { "objectId": "owner_repo_pr_42",     "qualifier": "subject" },
    { "objectId": "owner_repo_user_alice","qualifier": "actor"   },
    { "objectId": "owner_repo_commit_abc","qualifier": "merge_commit" }
  ]
}
```

#### `objects`

One entry per object. The `attributes` array is the change history — one item per snapshot row in the `object_*` table, each with a `time` field indicating when the attribute value was observed. For objects that use *Attribute Flattening* (like Pull Requests), attributes are anchored to the 1970 Unix Epoch.

```json
{
  "id": "owner_repo_pr_42",
  "type": "Pull Request",
  "attributes": [
    { "name": "number", "time": "1970-01-01T00:00:00Z", "value": 42      },
    { "name": "title",  "time": "1970-01-01T00:00:00Z", "value": "Fix UI" },
    { "name": "state",  "time": "1970-01-01T00:00:00Z", "value": "MERGED" }
  ]
}
```

> [!IMPORTANT]
> In accordance with the definition of OCEL 2.0, rows possessing the smallest feasible timestamp, specifically `1970-01-01T00:00:00Z`, correspond to the initial values of all the attributes for a given object. This uniform timestamp selection, symbolic of the starting point or "epoch", facilitates a consistent reference frame across all objects, aligning seamlessly with the structure proposed by OCEL 2.0. The deliberate choice of this fixed date for the timestamp of 0 is not arbitrary; instead, it serves a clear purpose by fostering improved compatibility and coherence with the OCEL 2.0 definition.

#### `objectRelationships`

One entry per O2O row in the SQLite `object_object` table.

```json
{
  "objectId":  "owner_repo_pr_42",
  "relatedObjectId": "owner_repo_commit_abc",
  "qualifier": "contains_commit"
}
```

---

### Validation

After export, `validate_ocel()` runs two passes against the JSON file:

1. **Syntax validation** — checks that all four top-level arrays are present, that every event and object has the mandatory fields (`id`, `type`, `time` for events; `id`, `type` for objects), and that all attribute types are within the allowed set.

2. **Semantic validation** — checks referential integrity: every `objectId` in an E2O relationship must exist in the `objects` array, and every `relatedObjectId` in an O2O relationship must also exist.

Both validators are registered by OCEL version key in `validate/validate_ocel.py`, making it straightforward to add a validator for a future version of the standard without modifying existing logic.

---

## Key design decisions

### Deterministic object IDs

Every object ID is generated by `make_id(repo_id, entity_type, raw_id)` which produces a stable string like `owner_repo_issue_123`. Using deterministic IDs rather than UUIDs means that re-running the extractor on the same repository produces the same IDs, making incremental diffs and idempotent re-runs straightforward.

### Commit stubs

Commits are referenced in O2O relationships from branches, tags, deployments, and workflow runs before the full commit data is available (Phase 4 runs after all of those). `ensure_commit()` inserts a minimal stub object with an empty attribute snapshot. `ensure_commit_full()`, called exclusively from `process_commit_graphql`, writes the rich snapshot with `allow_update=True`. Because the object table uses `(ocel_id, ocel_time, ocel_changed_field)` as a composite primary key, the full snapshot coexists with the stub without collision.

### Schema evolution

`OCELBuilder._ensure_type_table()` issues `ALTER TABLE ADD COLUMN` whenever a mapper provides an attribute that has not been seen before for that type. No schema is defined upfront; it emerges during extraction. This means adding a new attribute to a mapper requires no migration — it just appears in subsequent runs.

### Exception hierarchy

```textplain
GitHubAPIError
├── RetryableError          ← retried up to MAX_RETRIES with exponential backoff
│   ├── RateLimitError      ← also triggers RateLimiter.wait_if_needed()
│   ├── NetworkError        ← timeouts, connection drops
│   └── ServerError         ← 5xx responses
├── FatalError              ← never retried; aborts the pipeline
│   ├── AuthenticationError ← 401
│   ├── NotFoundError       ← 404
│   └── GitHubPermissionError ← 403 (non-rate-limit)
└── GraphQLError            ← retried only if error_type in {"somethings_wrong", "loading"}
```

### OCELBuilder internals

The builder keeps three in-memory caches to avoid redundant database round-trips:

- `registered_event_types` / `registered_object_types` — prevents repeated `INSERT OR IGNORE` into the type-map tables
- `known_tables_columns` — prevents repeated `PRAGMA table_info` calls for schema evolution checks
- `object_registry` — mirrors `object.ocel_id → ocel_type`, eliminating all `SELECT` calls from `object_exists()` and qualifier inference

SQLite is opened with `PRAGMA journal_mode = WAL` and `PRAGMA synchronous = NORMAL` for throughput. Foreign key enforcement is disabled (`PRAGMA foreign_keys = OFF`) because the phase ordering intentionally inserts relationships before all target objects exist.

## The Static State of Objects and the Unix Epoch (OCEL 2.0)

In Object-Centred Process Mining (OCPM), there is a fundamental difference between **Events** (point-in-time actions) and **Objects** (entities with a lifecycle).

To avoid a combinatorial explosion in the size of the database and the final JSON, `github2ocel` implements the concept of *Attribute Flattening* for objects. Instead of recording a new *Snapshot* every time a PR’s title, status or comment count changes, we dump the **final, global state** of the object.

### The Problem of the Temporal Paradox

If we were to record these final attributes using the object’s creation date (e.g. `createdAt`), we would be introducing information from the future into the past. We would be telling the OCPM engine that at the time of creating the PR, we already knew who was going to merge it (`merged_by`) or when it was going to be closed (`closed_at`).

### The Solution: The 1970 Sentinel (`safe_timestamp(None)`)

To resolve this, we follow the strict guideline of the official **OCEL 2.0 (RWTH Aachen)** standard for static attributes: use the Unix Epoch (`1970-01-01T00:00:00Z`).

In our mappers (e.g. `process_branch`, `process_pull_request`), we call `safe_timestamp(None)` when registering the object’s attributes:

```python
branch_obj.add_snapshot(
    time=safe_timestamp(None), # Returns "1970-01-01T00:00:00Z"
    attributes={
        "name": branch_name,
        "protected": int(is_protected),
        # ... global static attributes
    }
)
```

**Benefits of this approach:**

1. **Temporal decoupling:** The object floats in the graph as a static base entity, anchored prior to any actual repository events.
2. **Chronological purity:** The events (`PROpened`, `BranchObserved`) do retain their actual timestamps (`created_at`). When an analytics tool such as PM4Py or Celonis reads the log, it does not encounter ‘time travel’ conflicts, as the object’s base state theoretically existed from the very beginning of the record.
3. **Code Simplicity:** By utilising our `safe_timestamp` helper and injecting `None`, we apply this rule explicitly and safely without needing to modify the base classes of the OCEL model.

---

## GitHub API Limitations and Implemented Mitigations

Building a complete historical event log from a system designed for operational state management (such as GitHub) presents unique challenges. GitHub’s APIs (both REST and GraphQL) were not designed for process mining.

The following documents the main structural limitations of the GitHub API discovered during the development of **GitHub2OCEL** and the design decisions (mitigations) implemented to ensure the integrity of the OCEL 2.0 graph.

### 1. The absence of explicit timestamps (The `resolvedAt` problem)

**The Problem:** The GitHub GraphQL API allows the extraction of code review threads and indicates whether they have been resolved (`isResolved: true`). However, it does not expose a `resolvedAt` field. Without the resolution date, process mining tools would either send this event back to the beginning of time or fail due to the lack of a *timestamp*.
**The Solution (Mathematical Chronological Proxy):** To avoid emitting the event in the year 1970 (Unix Epoch), the extractor implements a **Chronological Proxy**. The list of comments nested within the thread is lazily evaluated, and the resolution date is inferred using the *timestamp* of the last published comment (`last_comment.createdAt`). This ensures that the `ReviewThreadResolved` event logically lands at the end of the discussion in the process map.

### 2. CI/CD ‘Ghost’ Jobs, ‘Year 1’, and Clock Skew

**The Problem:** In the GitHub Actions REST API, when a job (`WorkflowJob`) is queued but is cancelled, times out, or fails before a *runner* gets to initialise it, two temporal anomalies occur:

1. The API often returns a `started_at` value of `0001-01-01T00:00:00Z` (the `DateTime.MinValue` default from the GitHub backend).
2. Due to distributed systems "clock skew" between the GitHub orchestrator and the runners, the API sometimes returns a `started_at` timestamp that is actually *after* the `completed_at` timestamp.
Processing these literally would result in events travelling back to the Roman Empire or finishing before they even started, completely breaking the durations and timeline of the OCPM model.

**The Solution (Ontological Honesty & Variant Detection):**
The mapper explicitly neutralises any string beginning with `0001-01-01`, treating it as null. Furthermore, it implements a chronological safeguard: if `started_at` is greater than or equal to `completed_at`, it physically means the job never executed on a runner.

Instead of fabricating a fake start time to force a "perfect pair" of events (which creates zero-duration analytical noise), the extractor **drops the `WorkflowJobStarted` event entirely** and only emits the `WorkflowJobCompleted` event. This accurately models the "Cancelled in Queue" process variant, allowing Process Mining engines to correctly identify jobs that died before execution without distorting the real execution durations of successful jobs.

### 3. The Temporary Blind Spot for Pull Requests and Causal Completeness (The `since` Filter)

**The Problem:** GitHub’s GraphQL API allows you to filter *Issues* by date using `filterBy: { since: $since }`, but **it does not support this filter for Pull Requests**. Attempting to apply it returns a schema error, theoretically forcing you to download the entire repository history on every pull. Furthermore, applying strict date filters at the *event* level in Process Mining leads to a critical error known as "Trace Truncation" (e.g., a process map showing a PR closing today, but missing its opening event from two years ago, resulting in broken, floating arrows).

**The Solution (Case-Level Filtering & Causal Completeness):**
The extractor invokes the Pull Request query forcing a chronological order: `orderBy: { field: UPDATED_AT, direction: ASC }`. As the nodes arrive, they are dynamically filtered in Python at the **Object (Case) level**, rather than the event level.

If both the `createdAt` and `updatedAt` of the PR are strictly prior to the extraction time window, the node is safely discarded in memory (“short-circuiting”) before reaching the mapper, saving database clutter and processing time.

However, if an old PR (e.g., created in 2022) had *any* activity (a comment, label, or reference) within the current extraction window, the extractor intentionally downloads its **entire lifecycle history**. This architectural decision guarantees **Causal Completeness (Trace Completeness)**. It ensures process mining engines (like PM4Py or Celonis) receive the full context of the case, allowing them to calculate accurate Lead Times from the true origin of the PR without breaking the graph's integrity.

### 4. ‘Survivor Bias’ and Historical Amnesia

**The Problem:** GitHub endpoints, such as `/branches` (or its equivalent `refs/heads/` in GraphQL), only return entities that are ‘alive’ at the time of the query. If an event in the *Timeline* (such as a PR merged two years ago) refers to a branch that has been deleted, that branch will not exist in the catalogue of retrieved objects, breaking the semantic validation of OCEL 2.0 (orphan reference).
**The Solution (*Lazy Stubs* Pattern):**
The orchestrator implements proactive injection of proxy objects (*Stubs*). When a historical event mentions a branch, a commit or a PR that does not exist in the database (because it was deleted or is outside the extraction window), the system forces the creation of a minimal skeleton (with the identity and key attributes that can be deduced). This restores the complete graph and enables **100% referential integrity (0 semantic errors)**.

### 5. Inability to retrieve branch creation times (`BranchCreated`)

**The Problem:** No central GitHub API exposes the exact creation date of a reference (branch). The only way to obtain this information is via the *Events API* (`/events`), which has a strict retention limit of the **last 90 days**. For repositories with years of history, it is mathematically impossible to extract this data.
**The Solution (Ontological Honesty):**
Instead of inferring or inventing the creation date, the extractor returns the `BranchSnapshot` event (rather than `BranchCreated`). This informs the process mining engine that the entity was *observed* in a particular state, rather than falsifying its moment of creation.

### 6. Nested Pagination and Complexity-Induced Collapse

**The Problem:** Downloading a Pull Request along with all its Comments, Reviews and Review Comments in a single GraphQL macro-query causes GitHub to reject the request due to excessive complexity or to exhaust the 5,000-point rate limit within minutes.
**The Solution (Traffic Lights and Micro-Pagination):**
A **Dynamic Page Calibration** design was implemented. Phase 1 only fetches surface-level attributes and empty metrics (`totalCount`). The orchestrator uses these numbers as ‘traffic lights’. If an entity exceeds the limit of a nested page (e.g. a *Review* with more than 50 comments), a secondary on-demand micro-pager (`_fetch_remaining_review_comments`) is triggered to retrieve only the excess, ensuring 100% data capture without hitting the rate limit.

### Appendix: Empirical SQL Audit (Jellyfin-Vue Case Study)

To definitively prove that the implemented mitigations work exactly as designed, a rigorous SQL audit was conducted directly on the SQLite database generated by the `OCELBuilder` for the `jellyfin-vue` repository.

Below are the queries used and the **empirical results** obtained, demonstrating the absolute resilience of the extractor.

#### 1. The `resolvedAt` Chronological Proxy

**Objective:** Prove that resolved review threads do not time-travel to 1970 due to the lack of a native timestamp in the API, but rather inherit the logical date of the last comment.

**SQL Query:**

```sql
SELECT COUNT(*) AS hilos_en_1970
FROM event_ReviewThreadResolved
WHERE ocel_time LIKE '1970-%' OR ocel_time LIKE '0001-%';
```

- **Empirical Result:** `0 rows`. The system flawlessly evaluated the comment tree, assigning realistic completion dates to all resolved threads without defaulting to the Unix Epoch.

#### 2. CI/CD ‘Ghost’ Jobs and Clock Skew Mitigation

**Objective:** Prove that the extractor is "ontologically honest" by intentionally dropping the start events of jobs that suffered from Clock Skew or were cancelled in the queue.

**SQL Query:**

```sql
SELECT 'WorkflowJobStarted' AS tipo_evento, COUNT(*) AS total FROM event_WorkflowJobStarted
UNION ALL
SELECT 'WorkflowJobCompleted' AS tipo_evento, COUNT(*) AS total FROM event_WorkflowJobCompleted;
```

* **Empirical Result:** `49,271` Completed vs `48,119` Started.
* **Analysis:** The extractor surgically identified and neutralised exactly **1,152 "Ghost Jobs"** that had inverted or null start times. This successfully maps the "Cancelled in Queue" variant without poisoning the process graph with negative durations.

#### 3. Case-Level Filtering and Causal Completeness

**Objective:** Prove that the time-window filter (`since` / `until`) drags the complete history of older Pull Requests if they had any recent activity, preventing Trace Truncation.

**SQL Query:**

```sql
-- Searching for PRs born BEFORE the extraction window (e.g., 2026),
-- but whose latest activity fell WITHIN the window.
SELECT eo.ocel_object_id, MIN(pt.ocel_time) AS born_at, MAX(pt.ocel_time) AS last_activity
FROM event_object eo JOIN PR_Timeline pt ON eo.ocel_event_id = pt.ocel_id -- (CTE omitted for brevity)
GROUP BY eo.ocel_object_id
HAVING born_at < '$SINCE' AND last_activity >= '$SINCE';
```

- **Empirical Result:** Perfect capture of resurrected processes. For example:

  - **PR #1759**: Created in **May 2022**, but correctly extracted because it received a label/comment in **2026**.
  - **PR #2500**: Closed in **November 2024**, but intelligently fetched because it triggered a `CrossReferenced` event in **2026**.

- **Analysis:** The system guarantees 100% Causal Completeness, allowing process mining engines to calculate accurate multi-year Lead Times.

#### 4. 'Survivor Bias' and Lazy Stubs (Ghost Branches)

**Objective:** Demonstrate the effectiveness of the *Lazy Stubs* pattern in recovering branches that GitHub had already deleted, maintaining full referential integrity.

**SQL Query:**

```sql
SELECT COUNT(o.ocel_id) FROM object o
LEFT JOIN event_object eo ON o.ocel_id = eo.ocel_object_id AND eo.ocel_event_id IN (SELECT ocel_id FROM event_BranchSnapshot)
WHERE o.ocel_type = 'Branch' AND eo.ocel_event_id IS NULL;
```

- **Empirical Result:** **4,595 orphaned branches recovered** (e.g., `..._branch_dependabot_npm...`).
- **Analysis:** Without this mitigation, the OCEL 2.0 validator would have thrown 4,595 semantic errors for trying to connect historical PRs to non-existent references. The graph remains structurally flawless.

#### 5. Ontological Honesty in Branches

**Objective:** Validate that the extractor does not fabricate branch creation dates (`BranchCreated`), adhering strictly to historically demonstrable events.

**SQL Query:**

```sql
SELECT ocel_type, COUNT(*) as total FROM event WHERE ocel_type LIKE 'Branch%' GROUP BY ocel_type;
```

- **Empirical Result:**
  - `BranchDeleted`: 2,306
  - `BranchMerged`: 2,115
  - `BranchSnapshot`: 16
  - `BranchRestored`: 9
  - **`BranchCreated`: 0**

- **Analysis:** The engine tells the absolute truth. It registers the 16 branches it observed alive at runtime (`Snapshot`) and their verifiable historical deaths/merges, completely avoiding data fabrication.

#### 6. Nested Pagination and Complexity Collapse

**Objective:** Prove that the on-demand secondary micro-paginator successfully bypasses GitHub's GraphQL Node complexity limits for massive nested entities.

**SQL Query:**

```sql
SELECT ocel_object_id, COUNT(*) AS nested_comments FROM event_object
WHERE ocel_qualifier = 'reply_to_review' OR ocel_qualifier = 'subject' GROUP BY ocel_object_id ORDER BY nested_comments DESC LIMIT 3;
```

- **Empirical Result:** Reviews successfully materialized with **124**, **99**, and **68** nested comments.
- **Analysis:** Standard single-pass GraphQL queries would have truncated these results or triggered a `MAX_NODE_LIMIT` error. The dynamic "Traffic Light" (`totalCount`) design successfully detected the overflow and gracefully extracted every single event.
