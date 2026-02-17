import logging
import uuid
from typing import Dict, Any

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.utils.helper import make_id, calculate_duration, safe_timestamp
from github2ocel.transform.utils.ensure import ensure_commit, ensure_user
from shared.ocel.model.models  import Event, ObjectInstance

logger = logging.getLogger(__name__)


# REST Section (Workflow Runs)
def process_workflow_run(run: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Process a workflow run from REST API.
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

    # 2. Dependencies (Commit & User)
    head_sha = run.get("head_sha")
    commit_id = None
    if head_sha:
        # Pass timestamp so we reaffirm the commit existed/was relevant at this time
        commit_id = ensure_commit(builder, repo_id, head_sha, timestamp=ts_start)
        if commit_id:
            run_obj.add_rel(target_id=commit_id, qualifier="tests_commit")

    builder.insert_object(run_obj)

    # Events
    evt_start = Event(
        event_id=str(uuid.uuid4()),
        event_type=Activities.WORKFLOW_STARTED,
        time=ts_start,
        attributes={
            "trigger": run.get("event", "manual"),
            "attempt": int(run.get("run_attempt", 1))
        }
    )
    evt_start.add_rel(run_id, "run_started")
    evt_start.add_rel(repo_id, "context")
    if actor_id:
        evt_start.add_rel(actor_id, "actor")

    builder.insert_event(evt_start)

    # B. Completed
    if run.get("status") == "completed":
        evt_end = Event(
            event_id=str(uuid.uuid4()),
            event_type=Activities.WORKFLOW_COMPLETED,
            time=ts_update,
            attributes={
                "conclusion": run.get("conclusion", "unknown"),
                "duration_seconds": duration_seconds
            }
        )
        evt_end.add_rel(run_id, "run_completed")
        evt_end.add_rel(repo_id, "context")

        builder.insert_event(evt_end)

    # Process individual jobs as OCEL events
    jobs_data = run.get("jobs", [])
    for job in jobs_data:
        start_raw = job.get("started_at")
        end_raw = job.get("completed_at")

        duration = calculate_duration(start_raw, end_raw)

        job_evt = Event(
            event_id=f"job_{job['id']}", # Unique Job ID
            event_type="WorkflowJobCompleted",
            time=safe_timestamp(end_raw) or ts_update,
            attributes={
                "name": job.get("name"),
                "conclusion": job.get("conclusion"),
                "duration_seconds": duration,
                "runner_name": job.get("runner_name")
            }
        )

        # Relate Job EVENT to WorkflowRun OBJECT
        job_evt.add_rel(run_id, "belongs_to_run")

        builder.insert_event(job_evt)
