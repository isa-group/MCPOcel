import logging
from typing import List, Dict, Any
from .mappers.commits import process_commit_rest
from .mappers.devops import process_workflow_run
from .mappers.delivery import process_release, process_deployment

logger = logging.getLogger(__name__)

def run_rest_transformation(data: Dict[str, List[Dict[str, Any]]], builder, repo_id: str):
    """
    Orchestrates the REST transformation phase.
    'data' should contain keys: 'commits', 'runs', 'releases', 'deployments'
    """

    logger.info("Starting REST transformation pipeline...")

    # 1. Commits (Order matters: commits should be processed early)
    commits = data.get("commits", [])
    failed_commits = []
    for commit in commits:
        try:
            process_commit_rest(commit, builder, repo_id)
        except Exception as e:
            sha = commit.get("sha", "unknown")
            logger.error(f"Failed to process commit {sha}: {e}", exc_info=True)
            failed_commits.append(sha)

    if failed_commits:
        logger.warning(f"Failed commits: {len(failed_commits)}/{len(commits)}")

    # 2. Workflow Runs
    runs = data.get("runs", [])
    for run in runs:
        process_workflow_run(run, builder, repo_id)

    # 3. Delivery (Releases & Deployments)
    releases = data.get("releases", [])
    for rel in releases:
        process_release(rel, builder, repo_id)

    deployments = data.get("deployments", [])
    for dep in deployments:
        process_deployment(dep, builder, repo_id)

    logger.info("REST transformation phase completed successfully.")