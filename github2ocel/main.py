# stdlib
import os
import sys
from dotenv import load_dotenv
from datetime import datetime
from pathlib import Path
from config.settings import APIConfig

# Add parent directory to path for shared module access
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.logger.logging_config import setup_logging, get_logger, LoggingConfig

# internal
from shared.logger import get_logger, setup_logging
from github2ocel.config.settings import APIConfig, LoggingConfig
from github2ocel.transform.builder import OCELBuilder
from github2ocel.transform.mappers import (
    process_workflow_run,
    process_issue_node,
    process_commit_rest,
    process_release
)
from github2ocel.extractor.rest import fetch_workflow_runs, fetch_commits_rest, fetch_releases
from github2ocel.extractor.graphql import fetch_github_data
from github2ocel.validate.validate_ocel import validate_ocel

logger = get_logger(__name__)

# Config Repository & Output
STORAGE_DIR = Path("./storage")

def main():
    load_dotenv()
    # Setup Logging & API Config
    log_config = LoggingConfig.from_env()
    setup_logging(log_config)
    api_config = APIConfig.from_env()

    OWNER = os.getenv("GITHUB_OWNER", "statuscompliance")
    REPO = os.getenv("GITHUB_REPO", "status-backend")
    TOKEN = os.getenv("GITHUB_TOKEN")

    if not TOKEN:
        logger.critical("GitHub Token missing. Check your .env file.")
        return

    errors_occurred = False

    logger.info(f"--- Starting OCEL Pipeline for {OWNER}/{REPO} ---")



    builder = OCELBuilder()
    repo_id = f"repo_{OWNER}_{REPO}"
    builder.add_object(repo_id, "Repository", {"name": REPO})

    # GraphQL (Issues & PRs)
    try:
        nodes = fetch_github_data(OWNER, REPO, TOKEN, api_config, pages=None)
        for node in nodes:
            process_issue_node(node, builder, repo_id)
    except Exception:
        logger.exception("Error in GraphQL extraction phase")
        errors_occurred = True

    # REST Releases
    try:
        releases = fetch_releases(OWNER, REPO, TOKEN, api_config)
        for rel in releases:
            process_release(rel, builder, repo_id)
    except Exception:
        logger.exception("Error in Releases extraction phase")
        errors_occurred = True

    # REST Commits (With Conventional Commits)
    try:
        commits = fetch_commits_rest(OWNER, REPO, TOKEN, api_config, pages=None, max_detailed_total=50)
        for commit in commits:
            process_commit_rest(commit, builder, repo_id)
    except Exception:
        logger.exception("Error in Commits extraction phase")
        errors_occurred = True

    # REST Workflows
    try:
        runs = fetch_workflow_runs(OWNER, REPO, TOKEN, api_config, pages=None)
        for run in runs:
            if run.get("status") == "completed":
                process_workflow_run(run, builder, repo_id)
    except Exception:
        logger.exception("Error in Workflow extraction phase")
        errors_occurred = True

    if errors_occurred:
        logger.error("Data extraction encountered errors. Skipping export to protect data integrity.")
        return

    # Export & Validation
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"github_ocel_{timestamp}.json"
    output_path = STORAGE_DIR / filename

    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(f"--- QUERIES FINISHED ---")
    logger.info(f"Target file: {output_path}")

    try:
        builder.export_json(output_path)
        if validate_ocel(output_path):
            logger.info("Pipeline finished: OCEL 2.0 file is valid and ready for analysis.")
    except Exception:
        logger.exception("Error during export/validation")

if __name__ == "__main__":
    main()
