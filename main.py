import os
from dotenv import load_dotenv

# Configs & Utils
from config.settings import APIConfig, LoggingConfig
from utils.logging_config import setup_logging, get_logger


from transform.builder import OCELBuilder
from transform.mappers import (
    process_workflow_run,
    process_issue_node,
    process_commit_rest,
    process_release
)
from extractor.rest import fetch_workflow_runs, fetch_commits_rest, fetch_releases
from extractor.graphql import fetch_github_data
from validate.validate_ocel import validate_ocel

logger = get_logger(__name__)

# Config Repositoory & Output
OUTPUT_FILE = "./storage/github.ocel_v2.json"
REPO_OWNER = "statuscompliance"
REPO_NAME = "status-backend"

def main():
    load_dotenv()
    # Setup Logging & API Config
    log_config = LoggingConfig.from_env()
    setup_logging(log_config)
    api_config = APIConfig.from_env()

    logger.info(f"--- Starting OCEL Pipeline for {REPO_OWNER}/{REPO_NAME} ---")

    TOKEN = os.getenv("GITHUB_TOKEN")
    if not TOKEN:
        logger.critical("GitHub Token missing. Check your .env file.")
        return

    builder = OCELBuilder()
    repo_id = f"repo_{REPO_OWNER}_{REPO_NAME}"
    builder.add_object(repo_id, "Repository", {"name": REPO_NAME})

    # GraphQL (Issues & PRs)
    try:
        nodes = fetch_github_data(REPO_OWNER, REPO_NAME, TOKEN, api_config)
        for node in nodes:
            process_issue_node(node, builder, repo_id)
    except Exception:
        logger.exception("Error in GraphQL extraction phase")

    # REST Releases
    try:
        releases = fetch_releases(REPO_OWNER, REPO_NAME, TOKEN, api_config)
        for rel in releases:
            process_release(rel, builder, repo_id)
    except Exception:
        logger.exception("Error in Releases extraction phase")

    # REST Commits (With Conventional Commits)
    try:
        commits = fetch_commits_rest(REPO_OWNER, REPO_NAME, TOKEN, api_config, pages=2, max_detailed_total=50)
        for commit in commits:
            process_commit_rest(commit, builder, repo_id)
    except Exception:
        logger.exception("Error in Commits extraction phase")

    # REST Workflows
    try:
        runs = fetch_workflow_runs(REPO_OWNER, REPO_NAME, TOKEN, api_config, pages=2)
        for run in runs:
            if run.get("status") == "completed":
                process_workflow_run(run, builder, repo_id)
    except Exception:
        logger.exception("Error in Workflow extraction phase")

    # Export & Validation
    try:
        builder.export_json(OUTPUT_FILE)
        if validate_ocel(OUTPUT_FILE):
            logger.info("Pipeline finished: OCEL 2.0 file is valid and ready for analysis.")
    except Exception:
        logger.exception("Error during export/validation")

if __name__ == "__main__":
    main()