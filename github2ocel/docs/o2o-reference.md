# Object-to-object relationship reference

Object-to-object (O2O) relationships encode structural and semantic connections between objects independently of any event. In the OCEL 2.0 JSON format these appear under `objectRelationships`; in the SQLite database they live in the `object_object` table (`ocel_source_id`, `ocel_target_id`, `ocel_qualifier`).

The qualifier string is the exact value written to the database and exported to JSON.

## Index

- [Object-to-object relationship reference](#object-to-object-relationship-reference)
  - [Index](#index)
  - [Repository, Milestone, Branch, Tag](#repository-milestone-branch-tag)
  - [Issues](#issues)
  - [Pull Requests](#pull-requests)
  - [Comments and Reviews](#comments-and-reviews)
  - [Commits and Files](#commits-and-files)
  - [Releases and Deployments](#releases-and-deployments)
  - [Workflow Runs, Jobs, and Discussions](#workflow-runs-jobs-and-discussions)

---

## Repository, Milestone, Branch, Tag

| Source | Qualifier | Target | Notes |
| :---: | :---: | :---: | --- |
| `Milestone` | `contained_in` | `Repository` | |
| `Milestone` | `created_by` | `User` | |
| `Branch` | `contained_in` | `Repository` | |
| `Branch` | `last_author` | `User` | Login of the last committer on the branch at extraction time |
| `Branch` | `current_head` | `Commit` | HEAD commit at extraction time |
| `Tag` | `contained_in` | `Repository` | |
| `Tag` | `tags_commit` | `Commit` | |
| `Tag` | `created_by` | `User` | For annotated tags only; absent for lightweight tags created without a linked GitHub account |

---

## Issues

| Source | Qualifier | Target | Notes |
| :---: | :---: | :---: | --- |
| `Issue` | `contained_in` | `Repository` | |
| `Issue` | `created_by` | `User` | |
| `Issue` | `assigned_to` | `User` | One relationship per assignee; multi-assignee issues produce multiple rows |
| `Issue` | `has_label` | `Label` | One relationship per label |
| `Issue` | `belongs_to_milestone` | `Milestone` | Absent if no milestone is assigned |
| `Issue` | `closed_by` | `Pull Request` | Present when the issue was closed by a PR via closing keywords |
| `Issue` | `references` | `Pull Request` | Cross-reference in the issue body or comments |

---

## Pull Requests

| Source | Qualifier | Target | Notes |
| :---: | :---: | :---: | --- |
| `Pull Request` | `contained_in` | `Repository` | |
| `Pull Request` | `created_by` | `User` | |
| `Pull Request` | `assigned_to` | `User` | One row per assignee |
| `Pull Request` | `has_label` | `Label` | One row per label |
| `Pull Request` | `belongs_to_milestone` | `Milestone` | |
| `Pull Request` | `targets_branch` | `Branch` | Base (target) branch |
| `Pull Request` | `source_branch` | `Branch` | Head (source) branch |
| `Pull Request` | `references` | `Issue` | Cross-reference from PR body or comments |
| `Pull Request` | `linked_issue` | `Issue` | Formally linked via the sidebar ("Development" section) |
| `Pull Request` | `contains_commit` | `Commit` | One row per commit in the PR; populated in Phase 2 |

---

## Comments and Reviews

| Source | Qualifier | Target | Notes |
| :---: | :---: | :---: | --- |
| `Comment` | `authored_by` | `User` | |
| `Comment` | `comment_of` | `Issue` / `Pull Request` / `Review` / `Discussion` | Parent object; qualifier value is always `comment_of` regardless of parent type |
| `Comment` | `replies_to` | `Comment` | Present for threaded review comments with a `replyTo` reference |
| `Comment` | `on_file` | `File` | Review comments only; requires `complete` profile |
| `Comment` | `in_repo` | `Repository` | |
| `Review` | `belongs_to_pr` | `Pull Request` | |
| `Review` | `submitted_by` | `User` | |
| `Review` | `reviewed_at_commit` | `Commit` | The commit that was HEAD when the review was submitted |

---

## Commits and Files

| Source | Qualifier | Target | Notes |
| :---: | :---: | :---: | --- |
| `Commit` | `belongs_to` | `Repository` | Written for every commit (including stubs) |
| `Commit` | `authored_by` | `User` | |
| `Commit` | `committed_by` | `User` | Absent when committer equals author |
| `Commit` | `signed_by` | `User` | GPG / SSH verified commits with a linked GitHub account |
| `Commit` | `references_issue` | `Issue` | Closing keywords detected in the commit message |
| `Commit` | `tested_by` | `WorkflowRun` | Present when the workflow run's `head_sha` matches the commit |
| `Commit` | `modifies_file_added` | `File` | `complete` profile only |
| `Commit` | `modifies_file_modified` | `File` | `complete` profile only |
| `Commit` | `modifies_file_removed` | `File` | `complete` profile only |
| `Commit` | `modifies_file_renamed` | `File` | Target file after rename |
| `Commit` | `modifies_file_renamed_from` | `File` | Source file before rename |

---

## Releases and Deployments

| Source | Qualifier | Target | Notes |
| :---: | :---: | :---: | --- |
| `Release` | `contained_in` | `Repository` | |
| `Release` | `created_by` | `User` | |
| `Release` | `tagged_as` | `Tag` | |
| `Release` | `points_to_commit` | `Commit` | The tag's target commit |
| `Deployment` | `deployed_to` | `Repository` | Set at creation; qualifies the environment context |
| `Deployment` | `created_by` | `User` | |
| `Deployment` | `deploys_commit` | `Commit` | |
| `Deployment` | `deployed_from_branch` | `Branch` | Present when the deployment ref is a branch name |

---

## Workflow Runs, Jobs, and Discussions

| Source | Qualifier | Target | Notes |
| :---: | :---: | :---: | --- |
| `WorkflowRun` | `contained_in` | `Repository` | |
| `WorkflowRun` | `triggered_by` | `User` | The user who triggered the run (actor field in the API) |
| `WorkflowRun` | `tests_commit` | `Commit` | Linked via `head_sha` |
| `WorkflowRun` | `ran_on_branch` | `Branch` | Linked via `head_branch` |
| `WorkflowRun` | `validates_pr` | `Pull Request` | Present for runs triggered by `pull_request` or `pull_request_target` events |
| `WorkflowRun` | `retry_of` | `WorkflowRun` | Links attempt N to attempt N−1 of the same run number |
| `WorkflowJob` | `job_of_run` | `WorkflowRun` | |
| `Discussion` | `contained_in` | `Repository` | |
| `Discussion` | `created_by` | `User` | |
| `Discussion` | `has_label` | `Label` | One row per label |
