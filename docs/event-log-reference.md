# Event log reference

## Index

- [Event log reference](#event-log-reference)
  - [Index](#index)
  - [Issues](#issues)
  - [Pull Requests](#pull-requests)
  - [Reviews](#reviews)
  - [Comments](#comments)
  - [Commits](#commits)
  - [Labels](#labels)
  - [Milestones](#milestones)
  - [Branches](#branches)
  - [Tags \& releases](#tags--releases)
  - [Deployments](#deployments)
  - [Workflow runs and jobs](#workflow-runs-and-jobs)
  - [Discussions](#discussions)

Every event in the log has exactly one timestamp (`ocel_time`) as required by the OCEL 2.0 metamodel. Each row in this document corresponds to one event type. The **E2O qualifiers** column lists the objects that participate in the event and the role (qualifier) they take on the event→object arc.

**Qualifier legend:**

| Symbol | Role |
| :---: | --- |
| 🔵 | Subject — the primary object the event is about |
| 🟢 | Context — repository or container |
| 🟡 | Actor / Reviewer — the user who triggered the event |
| 🟣 | Related artefact — an additional object involved |

---

## Issues

| Event type | E2O qualifiers | Key attributes |
| :---: | --- | :---: |
| `IssueOpened` | 🔵 `Issue`, 🟢 `Repository`, 🟡 `User (actor)` | — |
| `IssueClosed` | 🔵 `Issue`, 🟢 `Repository`, 🟡 `User (actor)` | `closer_type`, `closer_ref` |
| `IssueReopened` | 🔵 `Issue`, 🟢 `Repository`, 🟡 `User (actor)` | — |
| `IssueAssigned` | 🔵 `Issue (target)`, 🟡 `User (actor)`, 🟣 `User (assignee)` | — |
| `IssueUnassigned` | 🔵 `Issue (target)`, 🟡 `User (actor)`, 🟣 `User (unassigned)` | — |
| `IssueLinked` | 🔵 `Issue/PR (subject)`, 🟣 `Issue/PR (linked_to)` | `linked_type` |
| `IssueUnlinked` | 🔵 `Issue/PR (subject)` | — |
| `CrossReferenced` | 🔵 `Issue/PR (target)`, 🟣 `Issue/PR (referenced_by)` | `source_type` |

---

## Pull Requests

| Event type | E2O qualifiers | Key attributes |
| :---: | --- | :---: |
| `PROpened` | 🔵 `PR`,, 🟢 `Repository`,, 🟡 `User (actor)` | `is_draft` |
| `PRClosed` | 🔵 `PR`, 🟢 `Repository`, 🟡 `User (actor)` | `closer_type`, `closer_ref` |
| `PRMerged` | 🔵 `PR`, 🟡 `User (actor)`, 🟣 `Commit (merge_commit)` | `merge_ref` |
| `PRReopened` | 🔵 `PR`, 🟡 `User (actor)` | — |
| `PRAssigned` | 🔵 `PR (target)`, 🟡 `User (actor)`, 🟣 `User (assignee)` | — |
| `PRUnassigned` | 🔵 `PR (target)`, 🟡 `User (actor)`, 🟣 `User (unassigned)` | — |
| `PRForcePushed` | 🔵 `PR (target)`, 🟡 `User (actor)` | `before_sha`, `after_sha` |
| `PRConvertedToDraft` | 🔵 `PR`, 🟡 `User (actor)` | — |
| `PRReadyForReview` | 🔵 `PR`, 🟡 `User (actor)` | — |
| `PRCIState` | 🔵 `PR`, 🟢 `Repository` | `ci_state` |
| `PRReviewRequested` | 🔵 `PR (target)`, 🟡 `User (actor)`, 🟡 `User (reviewer)` | `reviewer_type` |
| `PRReviewRequestRemoved` | 🔵 `PR (target)`, 🟡 `User (actor)` | — |

---

## Reviews

All four review event types share the same E2O structure and attributes.

| Event type | E2O qualifiers | Key attributes |
| :---: | --- | :---: |
| `PRReviewApproved` | 🔵 `Review`, 🟢 `PR`, 🟡 `User (reviewer)`, 🟣 `Commit (reviewed_at_commit)`, 🟢 `Repository` | `body_length`, `comments_count`, `author_role` |
| `PRReviewCommented` | 🔵 `Review`, 🟢 `PR`, 🟡 `User (reviewer)`, 🟣 `Commit (reviewed_at_commit)`, 🟢 `Repository` | `body_length`, `comments_count`, `author_role` |
| `PRReviewChangesRequested` | 🔵 `Review`, 🟢 `PR`, 🟡 `User (reviewer)`, 🟣 `Commit (reviewed_at_commit)`, 🟢 `Repository` | `body_length`, `comments_count`, `author_role` |
| `PRReviewDismissed` | 🔵 `Review`, 🟢 `PR`, 🟡 `User (reviewer)`, 🟣 `Commit (reviewed_at_commit)`, 🟢 `Repository` | `body_length`, `comments_count`, `author_role` |
| `ReviewThreadResolved` | 🔵 `Review`/`Comment` , 🟢 `PR`, 🟡 `User (resolved_by)` | `thread_id`, `is_outdated`, `path` |

> `PRReviewChangesRequested` is the string used in the OCEL log. The constant in `activity.py` is `PR_REVIEW_CHANGES_REQUESTED`.

---

## Comments

| Event type | E2O qualifiers | Key attributes |
| :---: | --- | :---: |
| `CommentCreated` | 🔵 `Comment`, 🟢 `PR/Issue/Discussion/Review`, 🟡 `User (actor)`, 🟣 `File (on_file)`, 🟣 `Review (review_context)` | `body_length`, `is_edited`, `reactions_count`, `author_association` |
| `CommentEdited` | 🔵 `Comment`, 🟢 `PR/Issue/Discussion/Review`, 🟣 `File (on_file)`, 🟣 `Review (review_context)` | `comment_type` |

> `File (on_file)` and `Review (review_context)` are only present for inline review comments. They are absent from issue, PR-level, and discussion comments.

---

## Commits

| Event type | E2O qualifiers | Key attributes |
| :---: | --- | :---: |
| `CommitCreated` | 🔵 `Commit`, 🟢 `Repository`, 🟡 `User (authored_by)`, 🟡 `User (committed_by)`, 🟡 `User (signed_by)` | `intent`, `is_merge_commit`, `is_verified`, `ci_status` |

> `signed_by` is only present when the commit has a verified GPG or SSH signature and the signer's GitHub account is known.

---

## Labels

| Event type | E2O qualifiers | Key attributes |
| :---: | --- | :---: |
| `LabelAdded` | 🔵 `Issue/PR (target)`, 🟡 `User (actor)`, 🟣 `Label (label_applied)` | `label_name` |
| `LabelRemoved` | 🔵 `Issue/PR (target)`, 🟡 `User (actor)` | — |

---

## Milestones

| Event type | E2O qualifiers | Key attributes |
| :---: | --- | :---: |
| `MilestoneCreated` | 🔵 `Milestone`, 🟢 `Repository`, 🟡 `User (actor)` | `title`, `due_on` |
| `MilestoneClosed` | 🔵 `Milestone`, 🟢 `Repository`, 🟡 `User (actor)` | `title` |
| `MilestoneUpdated` | 🔵 `Milestone`, 🟢 `Repository`, 🟡 `User (actor)` | `title` |
| `MilestoneAssigned` | 🔵 `Issue/PR (target)`, 🟡 `User (actor)` | `milestone_title` |
| `MilestoneRemoved` | 🔵 `Issue/PR (target)`, 🟡 `User (actor)` | — |

---

## Branches

| Event type | E2O qualifiers | Key attributes |
| :---: | --- | :---: |
| `BranchSnapshot` | 🔵 `Branch`, 🟢 `Repository`, 🟡 `User`, 🟣 `Commit (head)` | — |
| `BranchMerged` | 🔵 `PR`, 🟡 `User`, 🟣 `Commit`, 🟣 `Branch (merged)`, 🟣 `Branch (into)` | `branch_name`, `merged_into` |
| `BranchDeleted` | 🔵 `PR`, 🟡 `User`, 🟣 `Branch (deleted)` | `branch_name` |
| `BranchRestored` | 🔵 `PR`, 🟡 `User`, 🟣 `Branch (restored)` | `branch_name` |

> `BranchSnapshot` represents the observed state of a branch at extraction time. GitHub does not expose branch creation timestamps, so this event's timestamp is the extraction time — not the actual branch creation time.

---

## Tags & releases

| Event type | E2O qualifiers | Key attributes |
| :---: | --- | :---: |
| `TagCreated` | 🔵 `Tag`, 🟢 `Repository`, 🟡 `User`, 🟣 `Commit (tagged)` | `version`, `is_annotated` |
| `ReleaseCreated` | 🔵 `Release`, 🟢 `Repository`, 🟡 `User` | `tag`, `is_draft` |
| `ReleasePublished` | 🔵 `Release`, 🟢 `Repository`, 🟡 `User`, 🟣 `Commit`, 🟣 `Tag` | `tag`, `assets_count` |

---

## Deployments

| Event type | E2O qualifiers | Key attributes |
| :---: | --- | :---: |
| `DeploymentCreated` | 🔵 `Deployment`, 🟢 `Repository`, 🟡 `User`, 🟣 `Commit (on_commit)`, 🟣 `Branch (on_branch)` | `environment`, `task` |
| `DeploymentSucceeded` | 🔵 `Deployment`, 🟢 `Repository` | `state`, `environment_url`, `log_url` |
| `DeploymentFailed` | 🔵 `Deployment`, 🟢 `Repository` | `state`, `description` |
| `DeploymentError` | 🔵 `Deployment`, 🟢 `Repository` | `state`, `description` |

---

## Workflow runs and jobs

| Event type | E2O qualifiers | Key attributes |
| :---: | --- | :---: |
| `WorkflowRunStarted` | 🔵 `WorkflowRun (run_started)`, 🟢 `Repository`, 🟡 `User`, 🟣 `Commit (on_commit)` | `trigger`, `attempt`, `head_branch` |
| `WorkflowRunCompleted` | 🔵 `WorkflowRun (run_completed)`, 🟢 `Repository` | `conclusion`, `duration_seconds` |
| `WorkflowJobStarted` | 🔵 `WorkflowJob (job_execution)`, 🟣 `WorkflowRun (job_of_run)` | — |
| `WorkflowJobCompleted` | 🔵 `WorkflowJob (job_completed)`, 🟣 `WorkflowRun (job_of_run)` | `conclusion`, `duration_seconds` |

> Each workflow run produces exactly two events (`WorkflowRunStarted` + `WorkflowRunCompleted`) and two events per job. Re-run attempts increment `attempt` and are linked via the O2O `retry_of` qualifier on the `WorkflowRun` object.

---

## Discussions

| Event type | E2O qualifiers | Key attributes |
| :---: | --- | :---: |
| `DiscussionCreated` | 🔵 `Discussion`, 🟢 `Repository`, 🟡 `User` | — |
| `DiscussionAnswered` | 🔵 `Discussion`, 🟢 `Repository`, 🟡 `User` | — |
