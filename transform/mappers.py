from .builder import OCELBuilder


def process_workflow_run(run, builder: OCELBuilder, repo_id):
    run_id = f"workflow_{run['id']}"

    # Create the WorkflowRun Object
    builder.add_object(run_id, "WorkflowRun", {
        "run_id": str(run["id"]),
        "name": run["name"],
        "status": run["status"]
    })

    # Link run to the repository
    related_objects = [run_id, repo_id]

    # Add the completion event
    builder.add_event(
        activity="WorkflowRunCompleted",
        timestamp=run["updated_at"],
        related_objects=related_objects,
        attributes={"conclusion": run["conclusion"]}
    )