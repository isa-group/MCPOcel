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
from shared.ocel.builder import OCELBuilder
from shared.ocel.validator import validate_ocel

# internal
from shared.logger import get_logger, setup_logging
from github2ocel.config.settings import APIConfig, LoggingConfig
from github2ocel.transform.builder import OCELBuilder

from github2ocel.transform.rest_mapper import (
    run_rest_transformation
)
from github2ocel.transform.graphql_mapper import (
    process_issue_node,
)
from github2ocel.extractor.rest import fetch_workflow_runs, fetch_commits_rest, fetch_releases, fetch_deployments
from github2ocel.extractor.graphql import fetch_github_data
from github2ocel.validate.validate_ocel import validate_ocel
from extractor.rest import fetch_workflow_runs, fetch_commits_rest, fetch_releases
from extractor.graphql import fetch_github_data


logger = get_logger(__name__)

# Config Repository & Output
STORAGE_DIR = Path("./storage")

def main():
    load_dotenv()
    # Setup Logging & API Config
    log_config = LoggingConfig.from_env()
    setup_logging(log_config)
    api_config = APIConfig.from_env()

    OWNER = os.getenv("GITHUB_OWNER")
    REPO = os.getenv("GITHUB_REPO")
    TOKEN = os.getenv("GITHUB_TOKEN")

    if not all([OWNER, REPO, TOKEN]):
        logger.critical("Configuration missing (OWNER/REPO/TOKEN). Check .env.")
        sys.exit(1)

    logger.info(f"--- Pipeline Start: {OWNER}/{REPO} ---")

    db_path = STORAGE_DIR / f"staging_{REPO}.db"
    with OCELBuilder(db_path=db_path) as builder:
        repo_id = f"repo_{OWNER}_{REPO}"
        builder.add_object(repo_id, "Repository", {
            "name": REPO,
            "full_name": f"{OWNER}/{REPO}",
            "visibility": "public"
        })

        errors = False

        # 1. GraphQL: Rich Structure (Issues & PRs)
        try:
            nodes = fetch_github_data(OWNER, REPO, TOKEN, api_config)
            for node in nodes:

                process_issue_node(node, builder, repo_id)
            logger.info(f"Successfully processed {len(nodes)} GraphQL nodes.")
        except Exception:
            logger.exception("GraphQL phase failed")
            errors = True

        # last_week = (datetime.now() - timedelta(days=7)).isoformat() + "Z"# Llamada al fetchertry:
        try:
            # 2. REST Phase (Data collection)
            rest_data = {
                "commits": fetch_commits_rest(
                    OWNER, REPO, TOKEN, api_config,
                    since=None, # last_week
                    max_detailed_total=50),
                "runs": fetch_workflow_runs(OWNER, REPO, TOKEN, api_config),
                "releases": fetch_releases(OWNER, REPO, TOKEN, api_config),
                "deployments": fetch_deployments(OWNER, REPO, TOKEN, api_config)
            }

            # 3. REST Transformation (One single call!)
            run_rest_transformation(rest_data, builder, repo_id)

        except Exception:
            logger.exception("REST phase failed")
            errors = True

        if errors:
            logger.error("Pipeline aborted due to extraction errors.")
            sys.exit(1)


        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = STORAGE_DIR / f"github_ocel_{REPO}_{timestamp}.json"
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            builder.export_json(output_path)
            stats = builder.get_stats()
            logger.info(f"Log generated: {stats['objects']} objects, {stats['events']} events.")
        except Exception:
            logger.exception("Export failed")
            sys.exit(1)


    if validate_ocel(output_path):
        logger.info("VALIDATION SUCCESS: OCEL 2.0 file is ready.")

if __name__ == "__main__":
    main()
