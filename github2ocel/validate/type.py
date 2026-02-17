from typing import Any, Dict, List, Optional
from datetime import datetime


# OCEL Primitive Type Mapping
OCEL_TYPE_MAP = {
    "string": str,
    "integer": int,
    "float": float,
    "boolean": bool,
    "time": str,  # validated separately
}


# ISO 8601 Validation
def is_valid_iso8601(value: str) -> bool:
    """
    Validate ISO 8601 datetime string (basic compliance).

    Accepts:
        1970-01-01T00:00:00Z
        1970-01-01T00:00:00+00:00
    """
    if not isinstance(value, str):
        return False

    try:
        # Handle trailing Z
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        datetime.fromisoformat(value)
        return True
    except Exception:
        return False


# Value Type Validation
def validate_ocel_value_type(
    value: Any,
    declared_type: str,
    context: str = ""
) -> List[str]:
    """
    Validate a value against a declared OCEL type.
    """
    errors: List[str] = []

    if declared_type not in OCEL_TYPE_MAP:
        errors.append(f"{context}Unknown OCEL type '{declared_type}'")
        return errors

    expected_python_type = OCEL_TYPE_MAP[declared_type]

    # Special handling for time
    if declared_type == "time":
        if not is_valid_iso8601(value):
            errors.append(f"{context}Invalid ISO 8601 time format: {value}")
        return errors

    # Special handling for float (allow int as valid float?)
    if declared_type == "float":
        if not isinstance(value, (float, int)):
            errors.append(
                f"{context}Expected float, got {type(value).__name__}"
            )
        return errors

    # Standard type check
    if not isinstance(value, expected_python_type):
        errors.append(
            f"{context}Expected {declared_type}, got {type(value).__name__}"
        )

    return errors


# Attribute Definition Registry Builder
def build_type_registry(
    type_definitions: List[Dict]
) -> Dict[str, Dict[str, str]]:
    """
    Build registry:

        {
            "create-order": {
                "total-items": "integer"
            }
        }
    """
    registry: Dict[str, Dict[str, str]] = {}

    for type_def in type_definitions:
        type_name = type_def.get("name")
        if not type_name:
            continue

        attr_map: Dict[str, str] = {}

        for attr in type_def.get("attributes", []):
            attr_name = attr.get("name")
            attr_type = attr.get("type")
            if attr_name and attr_type:
                attr_map[attr_name] = attr_type

        registry[type_name] = attr_map

    return registry


# Attribute Instance Validation
def validate_attributes_against_registry(
    instance_type: str,
    attributes: List[Dict],
    registry: Dict[str, Dict[str, str]],
    context: str = "",
    strict: bool = True
) -> List[str]:
    """
    Validate that:
        - Attribute exists in declared type
        - Value matches declared OCEL type

    strict=True:
        Reject undeclared attributes
    """
    errors: List[str] = []

    declared_attrs: Optional[Dict[str, str]] = registry.get(instance_type)

    if declared_attrs is None:
        errors.append(f"{context}Type '{instance_type}' not declared")
        return errors

    for attr in attributes:
        name = attr.get("name")
        value = attr.get("value")

        if not name:
            errors.append(f"{context}Attribute missing 'name'")
            continue

        if name not in declared_attrs:
            if strict:
                errors.append(
                    f"{context}Undeclared attribute '{name}' for type '{instance_type}'"
                )
            continue

        declared_type = declared_attrs[name]
        errors.extend(
            validate_ocel_value_type(
                value,
                declared_type,
                context=f"{context}{name}: "
            )
        )

    return errors
