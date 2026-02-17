import sys
from datetime import datetime
from pathlib import Path
from datetime import datetime, timezone
# shared
from shared.logger import setup_logging, get_logger
from shared.config.env import Env

# github2ocel
from github2ocel.config.context import RepoContext
from shared.ocel.builder import OCELBuilder
from github2ocel.transform.mappers.OCEL2Json import OCEL2JsonExporter
from github2ocel.extractor.extractor import run_extractor
from github2ocel.validate.validate_ocel import validate_ocel
from shared.ocel.model.models import ObjectInstance
from github2ocel.utils.summary import print_pipeline_audit
from github2ocel.utils.verify_extractor import verify_data_integrity

# Output directory
STORAGE_DIR = Path("./storage")


def main() -> None:
    # logging
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
    storage_dir = Env.path("STORAGE_DIR", default="./storage")
    if not storage_dir.exists():
        storage_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    db_filename = f"github_ocel_{ctx.repo}_{timestamp}.db"
    json_filename = f"github_ocel_{ctx.repo}_{timestamp}.json"

    db_path = storage_dir / db_filename
    json_path = storage_dir / json_filename

    repo_id = f"repo_{ctx.owner}_{ctx.repo}"
    extraction_success = False

    with OCELBuilder(db_path=db_path) as builder:

        now_ts = datetime.now(timezone.utc)

        repo_obj = ObjectInstance(object_id=repo_id, object_type="Repository")
        repo_obj.add_snapshot(
                time=now_ts,
                attributes={
                    "name": ctx.repo,
                    "full_name": fullname,
                    "visibility": ctx.visibility,
                    "owner": ctx.owner
                }
            )

        builder.insert_object(repo_obj)

        logger.info(f"Database initialized at: {db_filename}")

        stats_extractor, extraction_success = run_extractor(ctx, builder, repo_id)

        if extraction_success:
            logger.info("Iniciando auditoría de integridad de datos...")
            verify_data_integrity(stats_extractor, builder.stats)
            print_pipeline_audit(builder)
        else:
            logger.error("Pipeline aborted due to extraction errors.")
            sys.exit(1)

    if not db_path.exists():
        logger.critical(f"CRITICAL: Database file not found at {db_path}")
        sys.exit(1)

    logger.info(f"SUCCESS: SQLite DB created ({db_path.stat().st_size / 1024 / 1024:.2f} MB)")

    try:
        logger.info(f"Exporting to JSON: {json_path}")
        exporter = OCEL2JsonExporter(db_path)
        exporter.export(json_path)

        if json_path.exists():
            logger.info(f"SUCCESS: JSON OCEL 2.0 ready ({json_path.stat().st_size / 1024 / 1024:.2f} MB)")


    except Exception as e:
        logger.error(f"Failed to export JSON: {e}", exc_info=True)
        sys.exit(1)

    if validate_ocel(json_path):
        logger.info(f"VALIDATION SUCCESS: OCEL 2.0 file ready at {json_path}")
    else:
        logger.warning("File generated but validation FAILED.")

if __name__ == "__main__":
    main()
