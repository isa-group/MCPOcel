# shared
from shared.logger import  get_logger
from typing import Dict, Tuple
# github2ocel
from github2ocel.config.context import RepoContext
from github2ocel.client.github_client import GitHubClient
from shared.ocel.builder import OCELBuilder
from github2ocel.extractor.github.orchestador import Orchestrator

logger = get_logger(__name__)

logger = get_logger(__name__)


def run_extractor(
    ctx: RepoContext,
    builder: OCELBuilder,
    repo_id: str,
) -> Tuple[Dict[str, int], bool]:

    logger.info(f"--- Extractor Start: {ctx.owner}/{ctx.repo} ---")

    stats: Dict[str, int] = {
        "milestones": 0, "branches": 0, "tags": 0,
        "issues": 0, "issue_comments": 0,
        "prs": 0, "pr_commit_links": 0, "pr_comments": 0,
        "reviews": 0, "timeline_events": 0,
        "commits": 0,
        "deployments": 0, "workflow_runs": 0, "workflow_jobs": 0,
        "releases": 0, "discussions": 0, "overflow_prs": 0,
    }

    try:
        client = GitHubClient.from_context(ctx)
    except Exception as e:
        logger.critical(f"Failed to initialise GitHubClient: {e}")
        return stats, False

    orchestrator = Orchestrator(client, builder, repo_id, stats)
    success = orchestrator.run()

    client.print_rate_limit_stats()
    client.close()

    logger.info(f"Extractor {'OK' if success else 'FAILED'}")
    return stats, success
