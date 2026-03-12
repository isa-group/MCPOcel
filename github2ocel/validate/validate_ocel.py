import json
import logging
from pathlib import Path
from typing import Optional, Union

from .syntax import validate_ocel_structure
from .semantic import validate_ocel_semantics

logger = logging.getLogger(__name__)

# Validator registries (Strategy pattern, function-based)
SYNTAX_VALIDATORS = {
    "2.0": validate_ocel_structure,
}

SEMANTIC_VALIDATORS = {
    "2.0": validate_ocel_semantics,
}


# Helper: resolve OCEL version to supported validator key
def resolve_ocel_version(ocel: dict) -> Optional[str]:
    """
    Resolve OCEL version to a supported validator key.
    """

    # OCEL 2.0 JSON canónico
    if all(k in ocel for k in ("eventTypes", "objectTypes", "events", "objects")):
        return "2.0"
    return None


# Main orchestrator
def validate_ocel(ocel_path: Union[str, Path], schema_path: Optional[str] = None) -> bool:
    """
    Validate an OCEL file.

    Args:
        ocel_path: Path to OCEL JSON file
        schema_path: Reserved for future use (ignored)

    Returns:
        True if valid, False otherwise
    """
    if schema_path is not None:
        logger.debug("schema_path provided but currently ignored")
    
    logger.info("=" * 60)
    logger.info("Starting OCEL validation")
    logger.info("=" * 60)

    ocel_path = Path(ocel_path)

    # Load OCEL file
    try:
        logger.info(f"Loading OCEL file: {ocel_path}")
        with ocel_path.open("r", encoding="utf-8") as f:
            ocel = json.load(f)

        file_size_kb = ocel_path.stat().st_size / 1024
        logger.info(f"OCEL file loaded ({file_size_kb:.1f} KB)")
    except Exception as e:
        logger.exception(f"Failed to load OCEL file: {e}")
        return False

    # Resolve OCEL version and validators
    version_key = resolve_ocel_version(ocel)

    if version_key not in SYNTAX_VALIDATORS or version_key not in SEMANTIC_VALIDATORS:
        logger.error("File does not match any supported OCEL JSON format")
        logger.error(f"Supported versions: {', '.join(SYNTAX_VALIDATORS.keys())}")
        return False

    syntax_validator = SYNTAX_VALIDATORS[version_key]
    semantic_validator = SEMANTIC_VALIDATORS[version_key]

    logger.info(f"Using OCEL {version_key} validators")

    # Syntax / structure validation
    logger.info("\nPhase 1: Syntax validation")
    logger.info("-" * 60)

    structure_errors = syntax_validator(ocel)

    if structure_errors:
        logger.error(f"Syntax validation FAILED ({len(structure_errors)} errors)")
        for i, error in enumerate(structure_errors[:5], 1):
            logger.error(f"  {i}. {error}")
        if len(structure_errors) > 5:
            logger.error(f"  ... and {len(structure_errors) - 5} more errors")
        return False

    logger.info("Syntax validation PASSED")

    # Semantic validation
    logger.info("Phase 2: Semantic validation")
    logger.info("-" * 60)

    semantic_errors = semantic_validator(ocel)

    if semantic_errors:
        logger.error(f"Semantic validation FAILED ({len(semantic_errors)} errors)")
        for i, error in enumerate(semantic_errors[:5], 1):
            logger.error(f"  {i}. {error}")
        if len(semantic_errors) > 5:
            logger.error(f"  ... and {len(semantic_errors) - 5} more errors")
        return False

    logger.info("Semantic validation PASSED")

    # Final result
    logger.info("\n" + "=" * 60)
    logger.info("VALIDATION SUCCESS: OCEL file is valid")

    events = ocel.get("events", [])
    objects = ocel.get("objects", [])

    logger.info("")
    logger.info("Summary:")
    logger.info(f"  Events: {len(events)}")
    logger.info(f"  Objects: {len(objects)}")
    logger.info(f"  Event types: {len(ocel.get('eventTypes', {}))}")
    logger.info(f"  Object types: {len(ocel.get('objectTypes', {}))}")
    logger.info("")

    return True


# CLI entrypoint
def main() -> None:
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s - %(message)s"
    )

    if len(sys.argv) < 2:
        print("Usage: python -m ocel_validator <ocel_file.json>")
        sys.exit(1)

    result = validate_ocel(sys.argv[1])
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()