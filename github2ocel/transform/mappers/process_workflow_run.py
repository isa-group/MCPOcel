import logging
from typing import Dict, Any, Optional, Tuple

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.utils.helper import make_id, calculate_duration, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_commit, ensure_user
from shared.ocel.model.models import ObjectInstance

logger = logging.getLogger(__name__)


def process_workflow_run(
    run: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
) -> Optional[str]:
    """
    Process a workflow run from REST API.

    Objects:   WorkflowRun, WorkflowJob
    Events:    WorkflowRunStarted, WorkflowRunCompleted,
               WorkflowJobStarted, WorkflowJobCompleted
    O2O:       WorkflowRun → Repo         (contained_in)
               WorkflowRun → User         (triggered_by)
               WorkflowRun → Commit       (tests_commit)
               WorkflowRun → Branch       (ran_on_branch)    — from head_branch
               WorkflowRun → PullRequest  (validates_pr)     — from pull_requests[]
               WorkflowJob → WorkflowRun  (job_of_run)

    Returns run_id so the orchestrator can build the retry_of map.
    """
    workflow_name = run.get("name", "Unknown_workflow")
    run_raw_id    = run.get("id")

    if not run_raw_id:
        logger.warning(f"Skipping workflow run without ID (name: {workflow_name})")
        return None

    run_id = make_id(repo_id, "workflow", run_raw_id)
    ts_start = safe_timestamp(run.get("run_started_at") or run.get("created_at"))
    ts_update = safe_timestamp(run.get("updated_at"))

    duration_seconds = (
        calculate_duration(ts_start, ts_update)
        if run.get("status") == "completed" else None
    )

    # WorkflowRun object
    run_obj = ObjectInstance(object_id=run_id, object_type="WorkflowRun")
    run_obj.add_snapshot(
        time=ts_start,
        attributes={
            "run_id":        str(run_raw_id),
            "name":          workflow_name,
            "display_title": run.get("display_title", ""),
            "path":          run.get("path", ""),           # .github/workflows/xxx.yml
            "conclusion":    run.get("conclusion", "pending"),
            "status":        run.get("status", "unknown"),
            "run_number":    int(run.get("run_number", 0)),
            "run_attempt":   int(run.get("run_attempt", 1)),
            "event_trigger": run.get("event", "manual"),
            "head_branch":   run.get("head_branch", ""),
            "html_url":      run.get("html_url", ""),
        }
    )
    run_obj.add_rel(repo_id, "contained_in")

    # O2O → User (triggering_actor takes precedence over actor)
    actor_login = (
        (run.get("triggering_actor") or {}).get("login")
        or (run.get("actor") or {}).get("login")
    )
    actor_id = ensure_user(builder, repo_id, actor_login, timestamp=ts_start) if actor_login else None
    if actor_id:
        run_obj.add_rel(actor_id, "triggered_by")

    # O2O → Commit (head_sha)
    head_sha  = run.get("head_sha")
    commit_id = None
    if head_sha:
        commit_id = ensure_commit(builder, repo_id, head_sha, timestamp=ts_start)
        if commit_id:
            run_obj.add_rel(commit_id, "tests_commit")

    # O2O → Branch (head_branch — Branch objects seeded in Phase 0)
    head_branch = run.get("head_branch")
    if head_branch:
        branch_id = make_id(repo_id, "branch", head_branch)
        if builder.object_exists(branch_id):
            run_obj.add_rel(branch_id, "ran_on_branch")

    builder.insert_object(run_obj)

    # O2O → PullRequest(s) — present for pull_request / pull_request_target events
    for pr_ref in (run.get("pull_requests") or []):
        pr_number = pr_ref.get("number")
        if pr_number:
            pr_id = make_id(repo_id, "pr", pr_number)
            if builder.object_exists(pr_id):
                proxy = ObjectInstance(object_id=run_id, object_type="WorkflowRun")
                proxy.add_rel(pr_id, "validates_pr")
                builder.insert_object(proxy)

    # Event: WorkflowRunStarted
    create_event(
        builder=builder,
        event_type=Activities.WORKFLOW_STARTED,
        ts=ts_start,
        attributes={
            "trigger":     run.get("event", "manual"),
            "attempt":     int(run.get("run_attempt", 1)),
            "head_branch": run.get("head_branch", ""),
        },
        relationships=[
            (run_id,    "run_started"),
            (repo_id,   "context"),
            (actor_id,  "actor")     if actor_id  else None,
            (commit_id, "on_commit") if commit_id else None,
        ]
    )

    # Event: WorkflowRunCompleted
    if run.get("status") == "completed":
        create_event(
            builder=builder,
            event_type=Activities.WORKFLOW_COMPLETED,
            ts=ts_update,
            attributes={
                "conclusion":       run.get("conclusion", "unknown"),
                "duration_seconds": duration_seconds,
                "attempt":          int(run.get("run_attempt", 1)),
            },
            relationships=[
                (run_id,  "run_completed"),
                (repo_id, "context"),
            ]
        )

    # WorkflowJob objects + events
    for job in (run.get("extracted_jobs") or []):
        _process_job(job, builder, repo_id, run_id, ts_start, ts_update)

    return run_id


def apply_retry_links(
    run_attempt_map: Dict[Tuple[int, int], str],
    builder: OCELBuilder,
) -> int:
    """
    Link re-run attempts: attempt N → attempt N-1 via O2O (retry_of).

    Called by the orchestrator after all runs are inserted — a re-run's
    predecessor may not exist yet when the re-run node is first processed.

    Returns the number of retry links created.
    """
    retries = 0
    for (run_number, run_attempt), run_id in run_attempt_map.items():
        if run_attempt < 2:
            continue
        prev_id = run_attempt_map.get((run_number, run_attempt - 1))
        if prev_id and builder.object_exists(prev_id):
            proxy = ObjectInstance(object_id=run_id, object_type="WorkflowRun")
            proxy.add_rel(prev_id, "retry_of")
            builder.insert_object(proxy)
            retries += 1
    return retries


def _process_job(
    job: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
    run_id: str,
    run_ts_start: str,
    run_ts_update: str,
) -> None:
    job_raw_id = job.get("id")
    if not job_raw_id:
        logger.warning(f"Skipping job without ID in run {run_id}")
        return

    job_obj_id = make_id(repo_id, "job", job_raw_id)

    start_raw = job.get("started_at")
    end_raw   = job.get("completed_at")

    # Queued-then-cancelled jobs have completed_at but no started_at
    effective_start_raw = start_raw or end_raw
    ts_job_start = safe_timestamp(effective_start_raw) or run_ts_start
    ts_job_end   = safe_timestamp(end_raw) or run_ts_update
    duration     = calculate_duration(start_raw, end_raw)

    job_obj = ObjectInstance(object_id=job_obj_id, object_type="WorkflowJob")
    job_obj.add_snapshot(
        time=ts_job_start,
        attributes={
            "name":             job.get("name") or "",
            "runner_name":      job.get("runner_name") or "",
            "status":           job.get("status") or "unknown",
            "conclusion":       job.get("conclusion") or "pending",
            "duration_seconds": duration,
        }
    )
    job_obj.add_rel(run_id, "job_of_run")
    builder.insert_object(job_obj)

    # Event: WorkflowJobStarted
    if effective_start_raw:
        create_event(
            builder=builder,
            event_type=Activities.JOB_STARTED,
            ts=ts_job_start,
            attributes={"source": "rest_api"},
            relationships=[
                (job_obj_id, "job_execution"),
                (run_id,     "job_of_run"),
            ]
        )

    # Event: WorkflowJobCompleted
    if end_raw:
        create_event(
            builder=builder,
            event_type=Activities.JOB_COMPLETED,
            ts=ts_job_end,
            attributes={
                "conclusion":       job.get("conclusion"),
                "duration_seconds": duration,
            },
            relationships=[
                (job_obj_id, "job_completed"),
                (run_id,     "job_of_run"),
            ]
        )
