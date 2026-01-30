from typing import Dict, List
from .common import validate_required_keys, validate_type

def validate_ocel_structure(ocel: Dict) -> List[str]:
    """
    Validate OCEL 2.0 structure without jsonschema.

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    # Top-level required keys
    required_top = [
        "ocel:global-log",
        "ocel:global-event",
        "ocel:global-object",
        "ocel:events",
        "ocel:objects",
        "ocel:object-relationships"
    ]
    errors.extend(validate_required_keys(ocel, required_top))

    if errors:
        return errors  # Can't continue without top-level structure

    # Validate ocel:global-log
    global_log = ocel["ocel:global-log"]
    errors.extend(validate_type(global_log, dict, "ocel:global-log: "))

    if isinstance(global_log, dict):
        errors.extend(validate_required_keys(global_log, ["ocel:version"], "ocel:global-log."))

        version = global_log.get("ocel:version")
        if version and not str(version).startswith("2."):
            errors.append(f"ocel:global-log.ocel:version must be '2.0' or '2.x', got '{version}'")

    # Validate ocel:global-event
    global_event = ocel["ocel:global-event"]
    errors.extend(validate_type(global_event, dict, "ocel:global-event: "))

    if isinstance(global_event, dict):
        for activity, attrs in global_event.items():
            if not isinstance(attrs, list):
                errors.append(f"ocel:global-event.{activity}: Expected list, got {type(attrs).__name__}")
                continue

            for i, attr in enumerate(attrs):
                if not isinstance(attr, dict):
                    errors.append(f"ocel:global-event.{activity}[{i}]: Expected dict")
                    continue

                if "ocel:name" not in attr:
                    errors.append(f"ocel:global-event.{activity}[{i}]: Missing 'ocel:name'")
                if "ocel:type" not in attr:
                    errors.append(f"ocel:global-event.{activity}[{i}]: Missing 'ocel:type'")

    # Validate ocel:global-object (same structure as global-event)
    global_object = ocel["ocel:global-object"]
    errors.extend(validate_type(global_object, dict, "ocel:global-object: "))

    if isinstance(global_object, dict):
        for obj_type, attrs in global_object.items():
            if not isinstance(attrs, list):
                errors.append(f"ocel:global-object.{obj_type}: Expected list, got {type(attrs).__name__}")
                continue

            for i, attr in enumerate(attrs):
                if not isinstance(attr, dict):
                    errors.append(f"ocel:global-object.{obj_type}[{i}]: Expected dict")
                    continue

                if "ocel:name" not in attr:
                    errors.append(f"ocel:global-object.{obj_type}[{i}]: Missing 'ocel:name'")
                if "ocel:type" not in attr:
                    errors.append(f"ocel:global-object.{obj_type}[{i}]: Missing 'ocel:type'")

    # Validate ocel:events
    events = ocel["ocel:events"]
    errors.extend(validate_type(events, list, "ocel:events: "))

    if isinstance(events, list):
        for i, event in enumerate(events):
            if not isinstance(event, dict):
                errors.append(f"ocel:events[{i}]: Expected dict")
                continue

            required_event = ["ocel:eid", "ocel:activity", "ocel:timestamp", "ocel:omap", "ocel:vmap"]
            errors.extend(validate_required_keys(event, required_event, f"ocel:events[{i}]."))

            # Check types
            if "ocel:omap" in event:
                errors.extend(validate_type(event["ocel:omap"], list, f"ocel:events[{i}].ocel:omap: "))

            if "ocel:vmap" in event:
                errors.extend(validate_type(event["ocel:vmap"], dict, f"ocel:events[{i}].ocel:vmap: "))

    # Validate ocel:objects
    objects = ocel["ocel:objects"]
    errors.extend(validate_type(objects, list, "ocel:objects: "))

    if isinstance(objects, list):
        for i, obj in enumerate(objects):
            if not isinstance(obj, dict):
                errors.append(f"ocel:objects[{i}]: Expected dict")
                continue

            required_obj = ["ocel:oid", "ocel:type", "ocel:ovmap"]
            errors.extend(validate_required_keys(obj, required_obj, f"ocel:objects[{i}]."))

            # Check ovmap structure
            if "ocel:ovmap" in obj:
                ovmap = obj["ocel:ovmap"]
                errors.extend(validate_type(ovmap, dict, f"ocel:objects[{i}].ocel:ovmap: "))

                if isinstance(ovmap, dict):
                    for attr_name, attr_values in ovmap.items():
                        if not isinstance(attr_values, list):
                            errors.append(
                                f"ocel:objects[{i}].ocel:ovmap.{attr_name}: "
                                f"Expected list, got {type(attr_values).__name__}"
                            )
                            continue

                        for j, attr_val in enumerate(attr_values):
                            if not isinstance(attr_val, dict):
                                errors.append(
                                    f"ocel:objects[{i}].ocel:ovmap.{attr_name}[{j}]: Expected dict"
                                )
                                continue

                            if "ocel:time" not in attr_val:
                                errors.append(
                                    f"ocel:objects[{i}].ocel:ovmap.{attr_name}[{j}]: Missing 'ocel:time'"
                                )
                            if "ocel:value" not in attr_val:
                                errors.append(
                                    f"ocel:objects[{i}].ocel:ovmap.{attr_name}[{j}]: Missing 'ocel:value'"
                                )

    # Validate ocel:object-relationships
    obj_rels = ocel["ocel:object-relationships"]
    errors.extend(validate_type(obj_rels, list, "ocel:object-relationships: "))
    if isinstance(obj_rels, list):
        for i, rel in enumerate(obj_rels):
            if not isinstance(rel, dict):
                errors.append(f"ocel:object-relationships[{i}]: Expected dict")
                continue

            required_rel = ["ocel:sourceId", "ocel:targetId", "ocel:qualifier"]
            errors.extend(validate_required_keys(rel, required_rel, f"ocel:object-relationships[{i}]."))

    return errors
