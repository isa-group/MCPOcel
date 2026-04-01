# github2ocel

Extracts the complete activity history of a GitHub repository and converts it into an **OCEL 2.0** event log — the standard format for object-centric process mining.

The output is an **OCEL 2.0 JSON file** (plus an intermediate SQLite database) strictly validated against the official RWTH Aachen schema. It is guaranteed to be structurally and semantically valid, ready to be loaded into any process mining tool that supports the standard: PM4Py, ProM, Celonis, and other OCPM toolkits.

## Index

- [github2ocel](#github2ocel)
  - [Index](#index)
  - [What is OCEL 2.0?](#what-is-ocel-20)
    - [Why OCEL 2.0 for a GitHub repository?](#why-ocel-20-for-a-github-repository)
    - [Output formats](#output-formats)
  - [What gets extracted](#what-gets-extracted)
  - [🧬 Data Anatomy: What’s Inside the JSON?](#-data-anatomy-whats-inside-the-json)
    - [1. ‘Out-of-the-box’ Analytical Richness](#1-out-of-the-box-analytical-richness)
    - [2. The Native Object-to-Object (O2O) Graph](#2-the-native-object-to-object-o2o-graph)
    - [3. Intelligent Modelling and Polymorphism](#3-intelligent-modelling-and-polymorphism)
    - [4. Concurrency and True Parallelism in CI/CD](#4-concurrency-and-true-parallelism-in-cicd)
    - [5. Data Integrity](#5-data-integrity)
    - [💡 Use Cases: Questions this JSON can answer](#-use-cases-questions-this-json-can-answer)
  - [Documentation index](#documentation-index)
  - [Quick start](#quick-start)

---

## What is OCEL 2.0?

**OCEL 2.0** is the standard format for object-centric process mining (OCPM). Unlike classical XES logs — where every event belongs to exactly one case — OCEL 2.0 allows an event to be associated with multiple objects of different types simultaneously, and allows objects to carry attribute histories that evolve over time.

| Concept | OCEL 2.0 definition | In this log |
| :---: | --- | --- |
| **Event** | An execution of an activity at a specific timestamp, linked to ≥1 objects and carrying activity attribute values. | `PRMerged`, `CommitCreated`, `DeploymentSucceeded`, … |
| **Activity** | The type of event. Defines which attributes its instances can carry. | 50+ activity types; full list in [event-log-reference.md](./event-log-reference.md) |
| **Object** | A uniquely identifiable instance of an object type. Its attributes are recorded as timestamped snapshots — one row per change. | `Issue`, `Pull Request`, `Commit`, `WorkflowRun`, … |
| **Object type** | The class an object belongs to. Defines the attribute schema shared by all objects of that type. | 16 object types; full schema in [data-model.md](./data-model.md) |
| **E2O relationship** | A directed, qualified arc from an event to an object describing the role that object plays in the event. Every event must have at least one. | `subject`, `actor`, `context`, `merge_commit`, `on_commit`, … |
| **O2O relationship** | A directed, qualified arc between two objects, independent of any event. | `contains_commit`, `targets_branch`, `tested_by`, `retry_of`, … |
| **Qualifier** | The label on a relationship arc. Distinguishes multiple objects of the same type participating in the same event or relationship. | Full qualifier inventory in [o2o-reference.md](./o2o-reference.md) |

### Why OCEL 2.0 for a GitHub repository?

Classical process mining assumes one case per trace. A GitHub repository does not fit that model:

- A single **commit** appears in multiple PRs.
- A single **PR** touches multiple issues, triggers multiple workflow runs, and receives reviews from multiple users.
- A **deployment** simultaneously involves a commit, a branch, and an environment — none of which is "the" case.

OCEL 2.0 makes these many-to-many relationships first-class citizens. No flattening, no duplication, no artificial case notion required.

### Output formats

The two formats produced by this tool are fully equivalent representations of the same log.

| Format | Extension | Use |
| --- | :---: | --- |
| **JSON** | `.json` / `.jsonocel` | Primary deliverable. Human-readable. Supported by PM4Py, ProM, Celonis, and any tool that implements the OCEL 2.0 JSON schema. |
| **SQLite** | `.sqlite` / `.sqlite3` | Intermediate store. Queryable with any SQL tool. Follows the official OCEL 2.0 relational mapping exactly. |

---

## What gets extracted

| Domain | Artefacts |
| :---: | --- |
| **Issues & PRs** | Lifecycle events, comments, labels, milestones, assignments, timeline events |
| **Code review** | Reviews (approved / changes-requested / dismissed / commented), inline comments, review threads |
| **Commits** | Full commit graph on the default branch, Conventional Commits parsing, file-level change links |
| **DevOps** | Deployments with status transitions, workflow runs and jobs |
| **Releases & tags** | Releases, annotated and lightweight tags |
| **Discussions** | Discussion nodes and threaded comments |

---

## 🧬 Data Anatomy: What’s Inside the JSON?

The generated JSON file is not a simple audit log; it is a **temporal knowledge graph** designed specifically for Object-Centred Process Mining (OCPM). Unlike traditional extractions that flatten data and lose context, this log preserves the multidimensional reality of software development.

Here we highlight the key features of the extracted data that enable advanced analysis:

### 1. ‘Out-of-the-box’ Analytical Richness

The extractor pre-calculates and standardises critical business metrics so you don’t have to. Within the attributes of objects and events, you will find:

- **Code Metrics:** `additions`, `deletions`, `total_changes`, `changed_files` in Commit and PR objects.
- **DevOps Metrics:** `duration_seconds` pre-calculated for each `WorkflowJob` and `WorkflowRun`, along with their outcome (`success`, `failure`, `skipped`).
- **Social Metrics:** Broken-down reactions (`reactions_thumbs_up`, `reactions_heart`, etc.), participant count and the `author_association` attribute (to distinguish between *Core* members, contributors and bots such as `dependabot`).

Translated with DeepL.com (free version)

### 2. The Native Object-to-Object (O2O) Graph

The real magic of OCEL 2.0 lies in Object-to-Object (`O2O`) relationships. The JSON builds a neural network of your repository. For example, a single **Deployment** object contains direct relationships to:

- The repository (`deployed_to`).
- The actor or bot that deployed it (`created_by`).
- The specific branch (`deployed_from_branch`).
- The exact commit (`deploys_commit`).

**What is this for?** It allows you to trace the reverse path instantly: if a deployment fails in Production, the OCPM engine can jump directly to the line of code, the PR where it was discussed, and the review that approved it, without the need for complex `JOINs` in SQL.

### 3. Intelligent Modelling and Polymorphism

To avoid a combinatorial explosion of the schema, the data model applies intelligent design decisions:

- **The Unified `Comment` Object:** All comments (from Issues, Pull Requests, Code Reviews and Discussions) converge into a single object type.
- **Conversation Trees:** Using the `replies_to` qualifier, the JSON reconstructs exact conversation threads, enabling Social Network Analysis (SNA) and the measurement of real-time knowledge transfer.
- **Resolution Semantics:** Attributes such as `is_answer` in discussions allow the ‘noise’ to be separated from the definitive solution.

### 4. Concurrency and True Parallelism in CI/CD

GitHub Actions pipelines are inherently parallel. A traditional XES log would crash when attempting to model multiple jobs running in the same second.
Thanks to the `job_of_run` and `job_execution` relationships, this JSON perfectly encapsulates concurrency. A tool such as PM4Py will read the JSON and draw true parallel branches (logical AND gates), enabling the detection of infrastructure bottlenecks rather than false loops.

### 5. Data Integrity

The extraction pipeline applies strict heuristics to ensure the JSON is analytically pure:

- **0 Semantic Errors:** Implements a *‘Lazy Stubs’* pattern for deleted branches or historical commits. If an event references a past entity, the object will exist in the log. There are no orphaned references.
- **Time Sanitisation:** Removes GitHub API artefacts (such as jobs started on `0001-01-01` or undated events) using secure ‘Chronological Proxies’, ensuring the process map always flows forwards in time and the timeline remains unbroken.

---

### 💡 Use Cases: Questions this JSON can answer

With a simple upload to tools such as Celonis or PM4Py, this log answers high-level questions such as:

1. *What is the actual lead time from the first commit on a feature branch to its successful deployment to production?*
2. *Which files in the repository have the highest number of comments and rework loops during code reviews?*
3. *How much computing time (and money) is wasted on CI/CD runs that end in `failure` and require retries?*

---

## Documentation index

| File | Contents |
| :---: | --- |
| [installation.md](./docs/installation.md) | Requirements, environment variables, first run |
| [architecture.md](./docs/architecture.md) | Pipeline phases, module layout, key design decisions |
| [data-model.md](./docs/data-model.md) | OCEL object types and their attributes |
| [event-log-reference.md](./docs/event-log-reference.md) | Every event type: E2O qualifiers and key attributes |
| [o2o-reference.md](./docs/o2o-reference.md) | Object-to-object relationship graph |

---

## Quick start

```bash
cp .env.example .env
# Edit .env — set GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO at minimum
pip install -r requirements.txt
python -m github2ocel.main

# (Optional) Run the built-in strict OCEL 2.0 validator on the output
python -m github2ocel.validate.validate_ocel path/to/storage/github_ocel_repo_timestamp.json
```

Output lands in `./storage/` as `github_ocel_<repo>_<timestamp>.json`.
