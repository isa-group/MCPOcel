# GithubOcel

## Index

- [GithubOcel](#githubocel)
  - [Index](#index)
  - [Data model reference](#data-model-reference)
    - [Repository](#repository)
    - [Issue](#issue)
    - [Pull Request](#pull-request)
    - [Commit](#commit)
    - [Branch](#branch)
    - [Tag](#tag)
    - [Milestone](#milestone)
    - [Release](#release)
    - [Deployment](#deployment)
    - [WorkflowRun](#workflowrun)
    - [WorkflowJob](#workflowjob)
    - [Review](#review)
    - [Comment](#comment)
  - [User](#user)
    - [Label](#label)
    - [File](#file)
    - [Discussion](#discussion)

## Data model reference

This document describes every OCEL **object type** produced by the extractor: the attributes stored in its snapshot table, the qualifiers used for its O2O relationships, and any behavioural notes relevant to integration.

Object IDs follow the pattern `{owner}_{repo}_{type}_{raw_id}`, e.g. `octocat_hello-world_issue_42`. IDs are deterministic — re-running the extractor on the same repository produces the same IDs.

---

### Repository

A single `Repository` object is created per run and acts as the root context for all other objects.

**Attributes:**

| Attribute | Type | Description |
| --- | --- | --- |
| `name_with_owner` | string | `owner/repo` |
| `description` | string | Repository description |
| `created_at` | string (ISO 8601) | Creation timestamp |
| `updated_at` | string (ISO 8601) | Last metadata update |
| `pushed_at` | string (ISO 8601) | Last push |
| `default_branch` | string | e.g. `main` |
| `is_private` | integer (0/1) | |
| `is_fork` | integer (0/1) | |
| `is_archived` | integer (0/1) | |
| `stars` | integer | Stargazer count at extraction time |
| `forks` | integer | |
| `watchers` | integer | |
| `disk_usage_kb` | integer | |
| `primary_language` | string | |
| `license_spdx` | string | SPDX identifier |
| `has_issues` | integer (0/1) | |
| `has_discussions` | integer (0/1) | |
| `has_wiki` | integer (0/1) | |

---

### Issue

One object per issue. The snapshot is written at extraction time and is not updated when the issue changes state (state transitions are captured as events instead).

**Attributes:**

| Attribute | Type | Description |
| --- | --- | --- |
| `number` | integer | GitHub issue number |
| `title` | string | |
| `state` | string | `OPEN` or `CLOSED` |
| `state_reason` | string | `COMPLETED`, `NOT_PLANNED`, `REOPENED`, or empty |
| `created_at` | string | |
| `updated_at` | string | |
| `closed_at` | string | Empty if open |
| `locked` | integer (0/1) | |
| `is_pr_reference` | integer (0/1) | 1 if this was encountered as a PR cross-reference |
| `body_length` | integer | Character count of the issue body |
| `reactions_count` | integer | Total reaction count |
| `comments_count` | integer | Total comment count at extraction time |
| `labels_count` | integer | Number of labels at extraction time |

---

### Pull Request

**Attributes:**

| Attribute | Type | Description |
| --- | --- | --- |
| `number` | integer | |
| `title` | string | |
| `state` | string | `OPEN`, `CLOSED`, or `MERGED` |
| `is_draft` | integer (0/1) | |
| `created_at` | string | |
| `updated_at` | string | |
| `closed_at` | string | |
| `merged_at` | string | |
| `body_length` | integer | |
| `additions` | integer | Lines added (aggregate) |
| `deletions` | integer | Lines removed (aggregate) |
| `changed_files` | integer | |
| `commits_count` | integer | |
| `reviews_count` | integer | |
| `comments_count` | integer | |
| `reactions_count` | integer | |
| `head_ref` | string | Source branch name |
| `base_ref` | string | Target branch name |
| `merge_commit_sha` | string | Present only when merged |
| `ci_state` | string | Last CI rollup state at extraction time |
| `labels_count` | integer | |

---

### Commit

Commits are inserted as stubs in early phases (branch head, tag target, deployment SHA) and enriched with full data in Phase 4. Both snapshots coexist in the object history table.

**Attributes (full snapshot — Phase 4):**

| Attribute | Type | Description |
| --- | --- | --- |
| `sha` | string | Full commit SHA |
| `source` | string | Always `graphql` for Phase 4 commits |
| `additions` | integer | |
| `deletions` | integer | |
| `changed_files` | integer | |
| `authored_date` | string | |
| `author_login` | string | |
| `committer_login` | string | |
| `is_merge_commit` | integer (0/1) | |
| `cc_type` | string | Conventional Commit type (`feat`, `fix`, `chore`, …) or `other` |
| `cc_scope` | string | Conventional Commit scope, if present |
| `cc_subject` | string | Commit subject line (max 255 chars) |
| `cc_body_len` | integer | Character count of the commit body |
| `is_breaking` | integer (0/1) | 1 if `!` marker or `BREAKING CHANGE` in body |
| `is_conventional` | integer (0/1) | 1 if the message matches the Conventional Commits pattern |

> **Note on Conventional Commits parsing.** The parser uses a two-tier approach: first a structural regex extracts `type(scope)!: subject` regardless of the type name; then the extracted type is validated against the normative set (`feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`). A commit with an unrecognised type is still parsed structurally (`is_conventional=1`) but its `cc_type` will be the raw string, not one of the normative values.

---

### Branch

Branches are extracted via the REST API and do not carry a `created_at` field (GitHub does not expose branch creation time). The snapshot timestamp is the extraction time.

**Attributes:**

| Attribute | Type | Description |
| --- | --- | --- |
| `name` | string | Branch name |
| `is_default` | integer (0/1) | |
| `is_protected` | integer (0/1) | |
| `head_sha` | string | SHA of the HEAD commit at extraction time |

---

### Tag

**Attributes:**

| Attribute | Type | Description |
| --- | --- | --- |
| `name` | string | Tag name |
| `is_annotated` | integer (0/1) | 1 if this is an annotated tag (has a tagger object) |
| `target_sha` | string | SHA of the tagged commit |
| `message` | string | Tag message (annotated tags only) |
| `is_semver` | integer (0/1) | 1 if the tag name matches semver pattern |
| `major` | integer | semver major version, or null |
| `minor` | integer | semver minor version, or null |
| `patch` | integer | semver patch version, or null |
| `prerelease` | string | semver prerelease label, or null |

---

### Milestone

**Attributes:**

| Attribute | Type | Description |
| --- | --- | --- |
| `number` | integer | |
| `title` | string | |
| `state` | string | `OPEN` or `CLOSED` |
| `due_on` | string | Due date, or empty |
| `created_at` | string | |
| `closed_at` | string | |
| `description` | string | |
| `open_issues` | integer | Count at extraction time |
| `closed_issues` | integer | Count at extraction time |

---

### Release

**Attributes:**

| Attribute | Type | Description |
| --- | --- | --- |
| `name` | string | Release title |
| `tag_name` | string | Associated tag |
| `is_draft` | integer (0/1) | |
| `is_prerelease` | integer (0/1) | |
| `created_at` | string | |
| `published_at` | string | |
| `body_length` | integer | Character count of release notes |
| `assets_count` | integer | |

---

### Deployment

**Attributes:**

| Attribute | Type | Description |
| --- | --- | --- |
| `environment` | string | e.g. `production`, `staging` |
| `state` | string | Final state at extraction time |
| `task` | string | e.g. `deploy` |
| `ref` | string | Branch or tag deployed |
| `sha` | string | Commit SHA at the time of deployment |
| `description` | string | Max 255 chars |

---

### WorkflowRun

**Attributes:**

| Attribute | Type | Description |
| --- | --- | --- |
| `run_number` | integer | |
| `run_attempt` | integer | Increments on re-run |
| `workflow_name` | string | |
| `event` | string | Trigger event (`push`, `pull_request`, …) |
| `conclusion` | string | `success`, `failure`, `cancelled`, `skipped`, etc. |
| `head_branch` | string | |
| `head_sha` | string | |
| `created_at` | string | |
| `updated_at` | string | |
| `run_started_at` | string | |

---

### WorkflowJob

**Attributes:**

| Attribute | Type | Description |
| --- | --- | --- |
| `job_id` | integer | GitHub job ID |
| `name` | string | |
| `status` | string | |
| `conclusion` | string | |
| `started_at` | string | |
| `completed_at` | string | |
| `duration_seconds` | float | |
| `runner_name` | string | |

---

### Review

One object per PR review submission.

**Attributes:**

| Attribute | Type | Description |
| --- | --- | --- |
| `state` | string | `APPROVED`, `CHANGES_REQUESTED`, `COMMENTED`, `DISMISSED` |
| `submitted_at` | string | |
| `body_length` | integer | |
| `comments_count` | integer | Inline comment count in this review |
| `author_association` | string | e.g. `COLLABORATOR`, `MEMBER`, `OWNER` |

---

### Comment

A single `Comment` type covers issue comments, PR comments, review (inline) comments, and discussion comments. The `comment_type` attribute distinguishes them.

**Attributes:**

| Attribute | Type | Description |
| --- | --- | --- |
| `comment_type` | string | `issue`, `pr`, `review`, or `discussion` |
| `created_at` | string | |
| `updated_at` | string | |
| `body_length` | integer | |
| `is_edited` | integer (0/1) | |
| `reactions_count` | integer | |
| `author_association` | string | |
| `path` | string | File path (review comments only) |
| `line` | integer | Line number (review comments only) |
| `diff_hunk` | string | Diff context (review comments only) |
| `is_answer` | integer (0/1) | 1 if this comment is the accepted answer (discussions only) |

---

## User

**Attributes:**

| Attribute | Type | Description |
| --- | --- | --- |
| `login` | string | GitHub username |
| `git_name` | string | Git `user.name` (only for commits by users without a GitHub account) |
| `git_email` | string | Git `user.email` (same condition as above) |

---

### Label

**Attributes:**

| Attribute | Type | Description |
| --- | --- | --- |
| `name` | string | |
| `color` | string | Hex colour without `#` |
| `description` | string | |

---

### File

Created only when `EXTRACTION_PROFILE=complete`. One object per unique file path encountered across all extracted commits.

**Attributes:**

| Attribute | Type | Description |
| --- | --- | --- |
| `name` | string | Full file path relative to repository root |

---

### Discussion

**Attributes:**

| Attribute | Type | Description |
| --- | --- | --- |
| `number` | integer | |
| `title` | string | |
| `created_at` | string | |
| `updated_at` | string | |
| `body_length` | integer | |
| `is_answered` | integer (0/1) | |
| `reactions_count` | integer | |
| `comments_count` | integer | Total comment count |
| `category` | string | Discussion category name |
