import json
from jsonschema import validate, ValidationError
from shared.logger.logging_config import get_logger
from pathlib import Path

logger = get_logger(__name__)

def validate_ocel(ocel_path, schema_path=Path("schemas/ocel_2_0.json")):
    if schema_path is None:
        raise ValueError("Schema path cannot be None")

    logger.info("Starting OCEL validation...")

    # Load files for validation
    try:
        with open(ocel_path, "r", encoding="utf-8") as f:
            ocel = json.load(f)
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
    except Exception:
        logger.exception("Error reading OCEL or Schema files")
        return False

    # Validate Syntax against JSON Schema
    try:
        validate(instance=ocel, schema=schema)
        logger.info("OCEL Syntax validation: PASSED")
    except ValidationError as e:
        logger.error(f"OCEL Syntax validation: FAILED - {e.message}")
        return False

    # Validate Semantics (Object-Event relationships)
    logger.info("Starting semantic integrity check...")
    defined_objs = set(ocel.get("ocel:objects", {}).keys())
    errors = []

    events = ocel.get("ocel:events", {})
    for eid, event in events.items():
        for obj_id in event.get("ocel:omap", []):
            if obj_id not in defined_objs:
                errors.append(f"Event {eid} references non-existent object: {obj_id}")

    if errors:
        logger.error(f"Semantic validation: FAILED ({len(errors)} errors found)")
        # Log only the first error to avoid flooding but indicate there are more
        logger.error(f"First error detail: {errors[0]}")
        return False
    else:
        logger.info("OCEL Semantic validation: PASSED")
        logger.info("Validation process: COMPLETED SUCCESSFULLY")
        return True
