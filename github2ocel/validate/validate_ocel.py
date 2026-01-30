"""
OCEL 2.x Validator Orchestrator (No external dependencies)

Coordinates syntax and semantic validation based on OCEL version.
"""

import json
import logging
from pathlib import Path
from typing import Optional

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

    Examples:
        "2.0"   -> "2.0"
        "2.0.1" -> "2.0"
        "2.1"   -> "2.0" (fallback, unless explicitly supported)

    Returns:
        Version key (e.g. "2.0") or None if unsupported
    """
    global_log = ocel.get("ocel:global-log", {})
    raw_version = str(global_log.get("ocel:version", "")).strip()

    if not raw_version:
        logger.warning("Missing ocel:global-log.ocel:version, assuming OCEL 2.0")
        return "2.0"

    if raw_version.startswith("2."):
        return "2.0"

    return None


# Main orchestrator
def validate_ocel(ocel_path: str, schema_path: Optional[str] = None) -> bool:
    """
    Validate an OCEL file.

    Args:
        ocel_path: Path to OCEL JSON file
        schema_path: Reserved for future use (ignored)

    Returns:
        True if valid, False otherwise
    """
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

    # Quick rejection of old / custom formats
    if "eventTypes" in ocel or "objectTypes" in ocel:
        logger.error("=" * 60)
        logger.error("ERROR: This file uses an OLD custom OCEL format")
        logger.error("Expected OCEL 2.x keys:")
        logger.error("  - ocel:global-log")
        logger.error("  - ocel:global-event")
        logger.error("  - ocel:global-object")
        logger.error("  - ocel:events")
        logger.error("  - ocel:objects")
        return False

    # Resolve OCEL version and validators
    version_key = resolve_ocel_version(ocel)

    if version_key not in SYNTAX_VALIDATORS or version_key not in SEMANTIC_VALIDATORS:
        logger.error(f"Unsupported OCEL version: {ocel.get('ocel:global-log', {}).get('ocel:version')}")
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
    logger.info("\nPhase 2: Semantic validation")
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

    events = ocel.get("ocel:events", [])
    objects = ocel.get("ocel:objects", [])

    logger.info("")
    logger.info("Summary:")
    logger.info(f"  Events: {len(events)}")
    logger.info(f"  Objects: {len(objects)}")
    logger.info(f"  Event types: {len(ocel.get('ocel:global-event', {}))}")
    logger.info(f"  Object types: {len(ocel.get('ocel:global-object', {}))}")
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
