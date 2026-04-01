# Installation & configuration

## Requirements

- Python 3.12+
- A GitHub Personal Access Token (classic or fine-grained)
- Network access to `api.github.com` (or a GitHub Enterprise hostname)

---

## Installation

```bash
git clone <repo-url>
cd github2ocel
pip install -r requirements.txt
cp .env.example .env
```

---

## Environment variables

All configuration is read from `.env` (or from actual environment variables — the file is loaded via `python-dotenv` at startup).

### Required

| Variable | Example | Description |
| :---: | :---: | --- |
| `GITHUB_TOKEN` | `ghp_abc123…` | Personal Access Token. Requires `repo` (read) scope; add `read:org` for private org repos. |
| `GITHUB_OWNER` | `octocat` | Repository owner (user or organisation). |
| `GITHUB_REPO` | `hello-world` | Repository name. |

### Extraction scope

| Variable | Default | Description |
| :---: | :---: | --- |
| `EXTRACTION_PROFILE` | `standard` | Controls which phases run. See [Extraction profiles](#extraction-profiles). |
| `EXTRACT_SINCE_DAYS` | _(unset)_ | Limit extraction to the last N days. Unset = full history. |
| `EXTRACT_UNTIL_DAYS` | `0` | Upper bound of the time window in days back from now. `0` = today. |

### Output

| Variable | Default | Description |
| :---: | --- | --- |
| `STORAGE_DIR` | `./storage` | Directory where `.db` and `.json` output files are written. |

### Logging

| Variable | Default | Description |
| :---: | :---: | --- |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. Use `DEBUG` only when troubleshooting — it logs full HTTP headers including the auth token. |
| `LOG_FILE` | `logs/github_extractor.log` | Log file path. The directory is created automatically. |

### API performance

These settings rarely need to change. Tune them only if you hit persistent timeouts or secondary rate limits on large repositories.

| Variable | Default | Description |
| :---: | :---: | --- |
| `API_TIMEOUT` | `30` | HTTP request timeout in seconds. |
| `MAX_RETRIES` | `5` | Maximum retry attempts per request. |
| `RETRY_BACKOFF_MIN` | `2.0` | Minimum backoff in seconds (doubles on each attempt). |
| `RETRY_BACKOFF_MAX` | `60.0` | Backoff cap in seconds. |
| `GITHUB_MAX_PAGES` | _(unset)_ | Hard limit on paginated pages per resource. Unset = no limit. Useful for quick test runs. |
| `GITHUB_PER_PAGE` | `100` | Items per page for REST endpoints (max 100). |
| `GITHUB_GRAPHQL_PER_PAGE` | `50` | Items per page for GraphQL queries (max 100; keep ≤50 to avoid server timeouts on large nodes). |
| `MAX_COMMITS_FOR_FILES` | `0` | Maximum commits to enrich with file-level data in Phase 4b. `0` = unlimited. Only relevant when `EXTRACTION_PROFILE=complete`. |

### GitHub Enterprise

| Variable | Default | Description |
| :---: | --- | --- |
| `GITHUB_API_URL` | `https://api.github.com` | Override for GitHub Enterprise REST base URL. |
| `GITHUB_GRAPHQL_URL` | `https://api.github.com/graphql` | Override for GitHub Enterprise GraphQL endpoint. |
| `GITHUB_API_VERSION` | `2022-11-28` | X-GitHub-Api-Version header of the GitHub REST API |

---

## Extraction profiles

The profile controls which pipeline phases are enabled. Choosing a lighter profile significantly reduces API quota consumption and runtime.

| Profile | Includes | Use when |
| :---: | --- | --- |
| `minimal` | Issues, PRs, branches, tags, milestones, releases, commits, deployments, workflow runs, discussions | Quick overview; quota is limited |
| `standard` | Everything in `minimal` + PR reviews, timeline events, CI status checks | **Recommended default** |
| `complete` | Everything in `standard` + inline review comments, review threads, per-commit file changes | Full audit trail; high quota cost |

> **Quota guidance.** The `standard` profile on a repository with ~500 PRs and ~2 000 issues typically consumes 3 000–5 000 GraphQL points. The `complete` profile on the same repository can exceed 10 000 points. GitHub resets the GraphQL quota (5 000 points/hour for authenticated users) on a rolling basis — the extractor waits automatically when it hits the limit.

---

## First run

```bash
python -m github2ocel.main
```

The pipeline prints a phase-by-phase progress log and finishes with an integrity report:

```log
=============================== Pipeline Start: owner/repo ===============================

 - Setup       — Repo stats [OK] (1.2s)
 - Init        — Seed objects [OK] (3.4s)
 - Phase 1     — Core objects [OK] (12.7s)
 - Phase 2     — Per-node detail [OK] (8.1s)
 - Phase 3     — Reviews & Timeline [OK] (21.4s)
 - Phase 4     — Commits [OK] (5.9s)
 - Phase 4b    — Commit files [SKIPPED by profile 'standard']
 - Phase 5     — Releases [OK] (0.8s)
 - Phase 6     — DevOps [OK] (4.2s)
 - Phase 7     — Knowledge base [OK] (2.1s)
 - Phase 7b    — Discussion comments [SKIPPED (no overflow)]

SUCCESS: SQLite DB created (4.21 MB)
SUCCESS: JSON OCEL 2.0 ready (11.83 MB)
VALIDATION SUCCESS: OCEL 2.0 file ready at storage/github_ocel_myrepo_20260325_143021.json
```

---

## Validating an existing file

The validator can be run standalone against any previously generated file:

```bash
python -m github2ocel.validate.validate_ocel storage/github_ocel_myrepo_20260325_143021.json
```

It runs two passes: structural validation (required OCEL 2.0 keys and types) followed by semantic validation (referential integrity between events, objects, and relationships).

---

## Output files

Both files are written to `STORAGE_DIR` with the same timestamp suffix.

| File | Format | Description |
| :---: | --- | --- |
| `github_ocel_<repo>_<ts>.db` | SQLite | Intermediate store. Useful for ad-hoc SQL queries during development. |
| `github_ocel_<repo>_<ts>.json` | JSON | Standard OCEL 2.0 file. This is the primary deliverable. |

### SQLite schema

The database follows the OCEL 2.0 relational mapping exactly:

- `event` — base event table (`ocel_id`, `ocel_type`)
- `object` — base object table (`ocel_id`, `ocel_type`)
- `event_object` — E2O relationships (`ocel_event_id`, `ocel_object_id`, `ocel_qualifier`)
- `object_object` — O2O relationships (`ocel_source_id`, `ocel_target_id`, `ocel_qualifier`)
- `event_map_type` / `object_map_type` — type name → table name mapping
- `event_<TypeName>` — one table per event type, with type-specific attribute columns
- `object_<TypeName>` — one table per object type, with change-history rows (`ocel_id`, `ocel_time`, `ocel_changed_field`)
