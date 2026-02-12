from typing import Dict, List, Any

def validate_required_keys(data: Dict, required: List[str], context: str = "") -> List[str]:
    """Check if all required keys are present."""
    errors = []
    for key in required:
        if key not in data:
            errors.append(f"{context}Missing required key: '{key}'")
    return errors


def validate_type(value: Any, expected_type: type, context: str = "") -> List[str]:
    """Check if value is of expected type."""
    if not isinstance(value, expected_type):
        return [f"{context}Expected {expected_type.__name__}, got {type(value).__name__}"]
    return []