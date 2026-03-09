import logging
from typing import Dict, Any

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.utils.helper import make_id, calculate_duration, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_commit, ensure_user
from shared.ocel.model.models  import ObjectInstance

logger = logging.getLogger(__name__)


def process_workflow_run(run: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Process a workflow run from REST API.
    Creates WorkflowRun object, WorkflowJob objects with job_of_run O2O,
    and WorkflowJobStarted/Completed events.
    """
    workflow_name = run.get("name", "Unknown_workflow")
    run_raw_id = run.get("id")

    if not run_raw_id:
        logger.warning(f"Skipping workflow run without ID (name: {workflow_name})")
        return

    try:
        run_id = make_id(repo_id, "workflow", run_raw_id)
    except ValueError as e:
        logger.error(f"Failed to create workflow run ID: {e}")
        return

    # Time handling
    ts_start = safe_timestamp(run.get("run_started_at") or run.get("created_at"))
    ts_update = safe_timestamp(run.get("updated_at"))

    duration_seconds = calculate_duration(ts_start, ts_update) if run.get("status") == "completed" else None

    # Register Workflow Object
    run_obj = ObjectInstance(object_id=run_id, object_type="WorkflowRun")
    run_obj.add_snapshot(
        time=ts_start,
        attributes={
            "run_id": str(run_raw_id),
            "name": workflow_name,
            "conclusion": run.get("conclusion", "pending"),
            "status": run.get("status", "unknown"),
            "run_number": int(run.get("run_number", 0)),
            "event_trigger": run.get("event", "manual"),
            "html_url": run.get("html_url", "")
        }
    )
    run_obj.add_rel(target_id=repo_id, qualifier="run_on_repo")

    # Actor
    actor_login = run.get("triggering_actor", {}).get("login")
    actor_id = ensure_user(builder, repo_id, actor_login, timestamp=ts_start)
    if actor_id:
        run_obj.add_rel(target_id=actor_id, qualifier="triggered_by")

    # Dependencies (Commit & User)
    head_sha = run.get("head_sha")
    commit_id = None
    if head_sha:
        # Pass timestamp so we reaffirm the commit existed/was relevant at this time
        commit_id = ensure_commit(builder, repo_id, head_sha, timestamp=ts_start)
        if commit_id:
            run_obj.add_rel(target_id=commit_id, qualifier="tests_commit")

    builder.insert_object(run_obj)

    # Event: WorkflowRunStarted
    create_event(
        builder=builder,
        event_type=Activities.WORKFLOW_STARTED,
        ts=ts_start,
        attributes={
            "trigger": run.get("event", "manual"),
            "attempt": int(run.get("run_attempt", 1))
        },
        relationships=[
            (run_id, "run_started"),
            (repo_id, "context"),
            (actor_id, "actor") if actor_id else None
        ]
    )

    # Event: WorkflowRunCompleted
    if run.get("status") == "completed":
        create_event(
            builder=builder,
            event_type=Activities.WORKFLOW_COMPLETED,
            ts=ts_update,
            attributes={
                "conclusion": run.get("conclusion", "unknown"),
                "duration_seconds": duration_seconds
            },
            relationships=[
                (run_id, "run_completed"),
                (repo_id, "context")
            ]
        )

    # Process individual jobs as OCEL events
    jobs_data = run.get("extracted_jobs", [])
    for job in jobs_data:
        job_raw_id = job.get("id")
        if not job_raw_id:
            logger.warning(f"Skipping job without ID in workflow run {run_id}")
            continue

        try:
            job_obj_id = make_id(repo_id, "job", job_raw_id)
        except ValueError as e:
            logger.error(f"Failed to create job ID: {e}")
            continue


        start_raw = job.get("started_at")
        end_raw = job.get("completed_at")
        ts_job_start = safe_timestamp(start_raw) or ts_start
        duration = calculate_duration(start_raw, end_raw)

        # O2O: WorkflowJob -> WorkflowRun
        job_obj = ObjectInstance(object_id=job_obj_id, object_type="WorkflowJob")
        job_obj.add_snapshot(
            time=safe_timestamp(start_raw) or ts_start,
            attributes={
                "name": job.get("name"),
                "runner_name": job.get("runner_name"),
                "conclusion": job.get("conclusion", "pending")
            }
        )
        job_obj.add_rel(target_id=run_id, qualifier="job_of_run")
        builder.insert_object(job_obj)

        # Event: WorkflowJobStarted
        if start_raw:
            create_event(
                builder=builder,
                event_type=Activities.JOB_STARTED,
                ts=ts_job_start,
                attributes={"source": "rest_api"},
                relationships=[
                    (job_obj_id, "job_execution"),
                    (run_id, "belongs_to_run")
                ]
            )

        # Event: WorkflowJobCompleted
        if end_raw:
            create_event(
                builder=builder,
                event_type=Activities.JOB_COMPLETED,
                ts=safe_timestamp(end_raw) or ts_update,
                attributes={
                    "conclusion": job.get("conclusion"),
                    "duration_seconds": duration
                },
                relationships=[
                    (job_obj_id, "job_completed"),
                    (run_id, "belongs_to_run")
                ]
            )
