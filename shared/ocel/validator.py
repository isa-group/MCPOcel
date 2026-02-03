"""OCEL 2.0 Validator.

Validates Object-Centric Event Logs against the OCEL 2.0 JSON schema.
Includes both syntactic (JSON schema) and semantic (referential integrity) validation.
"""

import json
import sys
from pathlib import Path
from jsonschema import validate, ValidationError

# Resolve schema path relative to shared folder
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
SCHEMA_PATH = REPO_ROOT / "shared" / "schemas" / "ocel_2_0.json"

from shared.logger.logging_config import get_logger
from shared.ocel.constants import EVENTS, OBJECTS

logger = get_logger(__name__)


def validate_ocel(ocel_path: Path, schema_path: Path = Path(SCHEMA_PATH)) -> bool:
    """
    Validates an OCEL file against the OCEL 2.0 schema.
    
    Args:
        ocel_path: Path to OCEL JSON file to validate.
        schema_path: Path to OCEL 2.0 JSON schema file.
        
    Returns:
        True if validation passes, False otherwise.
        
    Raises:
        ValueError: If schema_path is not a file.
    """
    if not schema_path.is_file():
        raise ValueError("Schema path must be a file")

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

    # Validate Semantics (referential integrity)
    logger.info("Starting semantic integrity check...")
    defined_objs = {obj["id"] for obj in ocel.get(OBJECTS, [])}
    errors = []

    # Check event-to-object relationships (e2o)
    for event in ocel.get(EVENTS, []):
        for rel in event.get("relationships", []):
            if rel["objectId"] not in defined_objs:
                errors.append(
                    f"Event {event['id']} references non-existent object: {rel['objectId']}"
                )

    # Check object-to-object relationships (o2o)
    for obj in ocel.get(OBJECTS, []):
        for rel in obj.get("relationships", []):
            if rel["objectId"] not in defined_objs:
                errors.append(
                    f"Object {obj['id']} references non-existent object: {rel['objectId']}"
                )

    if errors:
        logger.error(f"Semantic validation: FAILED ({len(errors)} errors found)")
        logger.error(f"First error detail: {errors[0]}")
        return False
    else:
        logger.info("OCEL Semantic validation: PASSED")
        logger.info("Validation process: COMPLETED SUCCESSFULLY")
        return True
