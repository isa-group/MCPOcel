import logging
from typing import Dict, Any
from github2ocel.transform.builder import OCELBuilder
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.utils.helper import make_id, calculate_duration
from github2ocel.transform.utils.ensure import ensure_commit, ensure_user

logger = logging.getLogger(__name__)

# Graphql
def map_devops_events(node: Dict[str, Any], builder: OCELBuilder, pr_id: str) -> None:
    """
    Map the status of CI/CD (Checks/Workflows) linked to a PR.
    """
    rollup = node.get("statusCheckRollup")
    if not rollup:
        return

    check_nodes = rollup.get("contexts", {}).get("nodes", [])
    obs_meta = {"event_class": "observed", "source": "github_actions", "confidence": "high"}

    for run in check_nodes:
        if run.get("__typename") != "CheckRun":
            continue

        job_id = f"job_{run['id']}"

        builder.add_object(job_id, "WorkflowJob", {
            "name": run.get("name"),
            "url": run.get("detailsUrl")
        })

        # Relationship: The PR depends on the outcome of this Job.
        builder.add_object_relationship(pr_id, job_id, "validated_by")

        # Execution events
        if run.get("startedAt"):
            builder.add_event(
                Activities.JOB_STARTED,
                run["startedAt"],
                [builder.rel(job_id, "job"), builder.rel(pr_id, "pull_request")],
                obs_meta
            )

        if run.get("completedAt"):
            builder.add_event(
                Activities.JOB_COMPLETED,
                run["completedAt"],
                [builder.rel(job_id, "job"), builder.rel(pr_id, "pull_request")],
                {**obs_meta, "conclusion": run.get("conclusion")}
            )

# REST
def process_workflow_run(run: Dict[str, Any], builder: OCELBuilder,
                        repo_id: str) -> None:
    """
    Process a workflow run from REST API.
    Validates required fields and calculates duration.
    """
    workflow_name = run.get("name", "Unknown_workflow")
    if not run.get("id"):
        logger.warning(f"Skipping workflow run without ID (name: {workflow_name})")
        return

    try:
        run_id = make_id(repo_id, "workflow", run["id"])
    except ValueError as e:
        logger.error(f"Failed to create workflow run ID: {e}")
        return

    builder.add_object(run_id, "WorkflowRun", {
        "run_id": str(run["id"]),
        "name": workflow_name,
        "conclusion": run.get("conclusion", "pending")
    })

    # Ensure commit exists
    head_sha = run.get("head_sha")
    commit_id = None
    if head_sha:
        commit_id = ensure_commit(builder, repo_id, head_sha)

    actor_id = ensure_user(builder, run.get("actor", {}).get("login"))

    rels = [
        builder.rel(run_id, "target"),
        builder.rel(repo_id, "source")
    ]

    if commit_id:
        builder.add_object_relationship(run_id, commit_id, "triggered_by")
        rels.append(builder.rel(commit_id, "trigger"))

    if actor_id:
        rels.append(builder.rel(actor_id, "actor"))

    # Workflow started event
    if run.get("run_started_at"):
        try:
            builder.add_event(
                Activities.WORKFLOW_STARTED,
                run["run_started_at"],
                rels
            )
        except Exception as e:
            logger.error(f"Failed to create workflow started event: {e}")

    # Workflow completed event
    if run.get("status") == "completed" and run.get("updated_at"):
        duration = calculate_duration(
            run.get("run_started_at"),
            run.get("updated_at")
        )
        # Validate duration is reasonable
        if duration and duration < 0:
            logger.warning(f"Workflow {run['id']} has negative duration: {duration}s")
            duration = 0

        try:
            builder.add_event(
                Activities.WORKFLOW_COMPLETED,
                run["updated_at"],
                rels,
                {
                    "conclusion": run.get("conclusion", "unknown"),
                    "duration_seconds": duration or 0
                }
            )
        except Exception as e:
            logger.error(f"Failed to create workflow completed event: {e}")

