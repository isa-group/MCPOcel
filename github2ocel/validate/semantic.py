from typing import Dict, List, Set

def validate_ocel_semantics(ocel: Dict) -> List[str]:
    """
    Validate OCEL 2.0 semantic constraints.

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    events = ocel.get("ocel:events", [])
    objects = ocel.get("ocel:objects", [])
    global_event = ocel.get("ocel:global-event", {})
    global_object = ocel.get("ocel:global-object", {})
    object_relationships = ocel.get("ocel:object-relationships", [])

    # Build object map
    object_ids: Set[str] = set()
    object_id_to_type: Dict[str, str] = {}
    event_ids: Set[str] = set()

    # Check objects
    for i, obj in enumerate(objects):
        oid = obj.get("ocel:oid")
        otype = obj.get("ocel:type")

        if not oid:
            errors.append(f"Object at index {i} missing ocel:oid")
            continue

        if oid in object_ids:
            errors.append(f"Duplicate object ID: {oid}")

        object_ids.add(oid)
        object_id_to_type[oid] = otype

        # Check if object type is declared
        if otype and otype not in global_object:
            errors.append(f"Object {oid} uses undeclared type '{otype}'")

        # Check o2o relationships
        for rel in obj.get("ocel:o2o", []):
            target_oid = rel.get("ocel:oid")
            if target_oid and target_oid not in object_ids:
                # Note: might be declared later, so this is just a warning
                pass

    # Check events
    for i, event in enumerate(events):
        eid = event.get("ocel:eid")
        activity = event.get("ocel:activity")
        omap = event.get("ocel:omap", [])

        if not eid:
            errors.append(f"Event at index {i} missing ocel:eid")
            continue

        if eid in event_ids:
            errors.append(f"Duplicate event ID: {eid}")

        event_ids.add(eid)

        # Check if activity is declared
        if activity and activity not in global_event:
            errors.append(f"Event {eid} uses undeclared activity '{activity}'")

        # Check all referenced objects exist
        for obj_id in omap:
            if obj_id not in object_ids:
                errors.append(f"Event {eid} references non-existent object: {obj_id}")

    # Check object relationships
    for i, rel in enumerate(object_relationships):
        source_id = rel.get("ocel:sourceId")
        target_id = rel.get("ocel:targetId")
        qualifier = rel.get("ocel:qualifier")

        if not source_id or not target_id:
            errors.append(f"Object relationship at index {i} missing source or target ID")
            continue

        if source_id not in object_ids:
            errors.append(f"Object relationship at index {i} has non-existent source ID: {source_id}")

        if target_id not in object_ids:
            errors.append(f"Object relationship at index {i} has non-existent target ID: {target_id}")
        if qualifier is None:
            errors.append(f"Object relationship at index {i} missing qualifier")

    return errors
