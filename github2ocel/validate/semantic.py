from typing import Dict, List, Set

def validate_ocel_semantics(ocel: Dict) -> List[str]:
    """
    Valida las restricciones semánticas de OCEL 2.0 siguiendo el estándar JSON oficial.
    Verifica integridad referencial, tipos declarados y duplicados.
    """
    errors = []

    # Load main collections (Official OCEL 2.0 Standard)
    events = ocel.get("events", [])
    objects = ocel.get("objects", [])
    event_types = {et["name"] for et in ocel.get("eventTypes", [])}
    object_types = {ot["name"] for ot in ocel.get("objectTypes", [])}

    # Inventories for cross-validation
    object_ids: Set[str] = set()
    event_ids: Set[str] = set()

    # IDs
    for i, event in enumerate(events):
        eid = event.get("id")
        if not eid:
            errors.append(f"Event at index {i} is missing 'id'")
            continue
        if eid in event_ids:
            errors.append(f"Duplicate event ID: {eid}")
        event_ids.add(eid)

    for i, obj in enumerate(objects):
        oid = obj.get("id")
        if not oid:
            errors.append(f"Object at index {i} is missing 'id'")
            continue
        if oid in object_ids:
            errors.append(f"Duplicate object ID: {oid}")
        object_ids.add(oid)

    # Reference and Integrity Validation
    
    # Events
    for event in events:
        eid = event.get("id", "unknown")
        etype = event.get("type")

        # Check if the event type was declared
        if etype and etype not in event_types:
            errors.append(f"Event {eid} uses undeclared eventType '{etype}'")

        # Verify Event -> Object relationships
        # According to OCEL 2.0 standard: {‘objectId’: ‘o1’, “qualifier”: ‘item’}
        for rel in event.get("relationships", []):
            target_id = rel.get("objectId")
            if not target_id:
                errors.append(f"Event {eid} has a relationship missing 'objectId'")
                continue

            if target_id not in object_ids:
                errors.append(f"Event {eid} references non-existent object: {target_id}")

    # Objects
    for obj in objects:
        oid = obj.get("id", "unknown")
        otype = obj.get("type")

        # Check if the object type was declared
        if otype and otype not in object_types:
            errors.append(f"Object {oid} uses undeclared objectType '{otype}'")

        # Check Object Attributes (Snapshots)
        # OCEL 2.0 requires “time” in object attributes
        for attr in obj.get("attributes", []):
            if "time" not in attr:
                errors.append(f"Object {oid}, attribute '{attr.get('name')}': Missing required 'time' field")

    # Validate nested object-to-object (O2O) relationships
        for rel in obj.get("relationships", []):
            target_id = rel.get("objectId")
            if not target_id:
                errors.append(f"Object {oid} has a relationship missing 'objectId'")
                continue

            if target_id not in object_ids:
                errors.append(f"Object {oid} references non-existent object: {target_id}")

    return errors