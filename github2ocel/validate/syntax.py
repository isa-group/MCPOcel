from typing import Dict, List
from .common import validate_required_keys

def validate_ocel_structure(ocel: Dict) -> List[str]:
    """
    Validates OCEL 2.0 'Clean JSON' format structure.
    """
    errors = []

    # 1. Root Keys (Clean format uses camelCase, no prefixes)
    required_top = ["eventTypes", "objectTypes", "events", "objects"]
    errors.extend(validate_required_keys(ocel, required_top))
    if errors: return errors

    # 2. Event Types & Object Types
    for kind in ["eventTypes", "objectTypes"]:
        if not isinstance(ocel[kind], list):
            errors.append(f"{kind}: Expected list")
            continue
        for i, item in enumerate(ocel[kind]):
            if "name" not in item: errors.append(f"{kind}[{i}]: Missing 'name'")
            if "attributes" not in item: errors.append(f"{kind}[{i}]: Missing 'attributes'")

    # 3. Events
    events = ocel["events"]
    if not isinstance(events, list):
        errors.append("events: Expected list")
    else:
        for i, ev in enumerate(events):
            # Mandatory fields
            if "id" not in ev: errors.append(f"events[{i}]: Missing 'id'")
            if "type" not in ev: errors.append(f"events[{i}]: Missing 'type'")
            if "time" not in ev: errors.append(f"events[{i}]: Missing 'time'")

            # Attributes (List of {name, value})
            attrs = ev.get("attributes", [])
            if not isinstance(attrs, list):
                errors.append(f"events[{i}].attributes: Expected list")
            else:
                for j, at in enumerate(attrs):
                    if "name" not in at or "value" not in at:
                        errors.append(f"events[{i}].attributes[{j}]: Malformed attribute")

            # Relationships (List of {objectId, qualifier})
            rels = ev.get("relationships", [])
            if not isinstance(rels, list):
                errors.append(f"events[{i}].relationships: Expected list")
            else:
                for j, rel in enumerate(rels):
                    if "objectId" not in rel or "qualifier" not in rel:
                        errors.append(f"events[{i}].relationships[{j}]: Malformed relationship")

    # 4. Objects
    objects = ocel["objects"]
    if not isinstance(objects, list):
        errors.append("objects: Expected list")
    else:
        for i, obj in enumerate(objects):
            if "id" not in obj: errors.append(f"objects[{i}]: Missing 'id'")
            if "type" not in obj: errors.append(f"objects[{i}]: Missing 'type'")

            # Object Attributes must have 'time'
            attrs = obj.get("attributes", [])
            if not isinstance(attrs, list):
                errors.append(f"objects[{i}].attributes: Expected list")
            else:
                for j, at in enumerate(attrs):
                    if "name" not in at or "value" not in at or "time" not in at:
                        errors.append(f"objects[{i}].attributes[{j}]: Missing name, value, or time")

    return errors