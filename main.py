import os
from dotenv import load_dotenv

from config.settings import APIConfig, LoggingConfig
from utils.logging_config import setup_logging, get_logger

from transform.builder import OCELBuilder
from transform.mappers import process_workflow_run, process_issue_node, process_commit_rest
from extractor.rest import fetch_workflow_runs, fetch_commits_rest
from extractor.graphql import fetch_github_data
from validate.validate_ocel import validate_ocel

from utils.logging_config import setup_logging, get_logger

# Config
OUTPUT_FILE = "./storage/github.ocel_v1.json"
REPO_OWNER = "statuscompliance"
REPO_NAME = "status-backend"

logger = get_logger(__name__)

def main():
    load_dotenv()
    log_config = LoggingConfig.from_env()
    setup_logging(log_config)

    api_config  = APIConfig.from_env()

    logger.info("--- Starting GitHub OCEL Extraction Process ---")

    TOKEN = os.getenv("GITHUB_TOKEN")
    if not TOKEN:
        logger.critical("Error: Github token not found in environment variables.")
        return

    builder = OCELBuilder()
    repo_id = f"repo_{REPO_OWNER}_{REPO_NAME}"
    builder.add_object(repo_id, "Repository", {"name": REPO_NAME})

    # GraphQL
    try:
        logger.info("Fetching data from GitHub GraphQL API...")
        nodes = fetch_github_data(REPO_OWNER, REPO_NAME, TOKEN, api_config)
        for node in nodes:
            process_issue_node(node, builder, repo_id)

        logger.info(f"Successfully processed {len(nodes)} nodes from GraphQL.")
    except Exception as e:
        logger.exception("Unexpected error during GraphQL data extraction")

    # REST Workflows
    try:
        logger.info("Fetching workflow runs from REST API...")
        runs = fetch_workflow_runs(REPO_OWNER, REPO_NAME, TOKEN, api_config,pages=2)

        completed_count = 0
        for run in runs:
            if run["status"] == "completed":
                process_workflow_run(run, builder, repo_id)
                completed_count += 1

        logger.info(f"Processed {completed_count} completed workflow runs.")
    except Exception as e:
        logger.exception("Unexpected error during Workflow runs extraction")

    # REST Commits
    try:
        logger.info("Fetching commits from REST API...")
        commits = fetch_commits_rest(REPO_OWNER, REPO_NAME, TOKEN, api_config, pages=1) # Only 1 page
        for commit in commits:
            process_commit_rest(commit, builder, repo_id)

        logger.info(f"Successfully processed {len(commits)} commits.")
    except Exception as e:
        logger.exception("Unexpected error during Commits extraction")

    # Export
    try:
        logger.info(f"Exporting OCEL data to: {OUTPUT_FILE}")
        builder.export_json(OUTPUT_FILE)

    # Validation
        logger.info("Validating exported OCEL file...")
        validate_ocel(OUTPUT_FILE)

        logger.info("Process completed successfully.")
    except Exception:
        logger.exception("Error during export or validation phase")

if __name__ == "__main__":
    main()
