import sys
from datetime import datetime
from pathlib import Path

# shared
from shared.logger import setup_logging, get_logger
from shared.config.env import load_env

# github2ocel
from github2ocel.config.context import RepoContext
from github2ocel.transform.builder import OCELBuilder
from github2ocel.extractor.extractor import run_extractor
from github2ocel.validate.validate_ocel import validate_ocel
from extractor.rest import fetch_workflow_runs, fetch_commits_rest, fetch_releases
from extractor.graphql import fetch_github_data


# Output directory
STORAGE_DIR = Path("./storage")


def main() -> None:
    # Environment & logging
    load_env(Path(".env"))
    setup_logging()
    logger = get_logger(__name__)

    try:
        ctx = RepoContext.from_env()
    except Exception as e:
        logger.critical(f"Failed to load context: {e}")
        sys.exit(1)

    fullname = f"{ctx.owner}/{ctx.repo}"
    logger.info(f"--- Pipeline Start: {fullname} ---")

    # Ensure storage exists
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    db_path = STORAGE_DIR / f"staging_{ctx.repo}.db"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = STORAGE_DIR / f"github_ocel_{ctx.repo}_{timestamp}.json"

    repo_id = f"repo_{ctx.owner}_{ctx.repo}"
    extraction_success = False

    with OCELBuilder(db_path=db_path) as builder:
        builder.add_object(
            repo_id,
            "Repository",
            {
                "name": ctx.repo,
                "full_name": fullname,
                "visibility": ctx.visibility,
            },
        )

        # Ejecutamos la extracción y capturamos el resultado (True/False)
        extraction_success = run_extractor(ctx, builder, repo_id)

        if not extraction_success:
            logger.error("Extraction failed. Aborting export.")
        else:
            # 3.3 Exportación (Solo si la extracción fue bien)
            try:
                logger.info("Exporting to JSON-OCEL...")
                builder.export_json(output_path)
                stats = builder.get_stats()
                logger.info(f"Export done: {stats.get('objects', '?')} objects, {stats.get('events', '?')} events.")
            except Exception:
                logger.exception("Export failed during JSON generation")
                extraction_success = False


    # 4. Validate
    if not extraction_success:
        logger.error("Exiting due to errors.")
        sys.exit(1)

    if validate_ocel(output_path):
        logger.info(f"VALIDATION SUCCESS: OCEL 2.0 file ready at {output_path}")
    else:
        logger.warning("File generated but validation FAILED.")


if __name__ == "__main__":
    main()
