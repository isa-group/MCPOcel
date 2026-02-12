from typing import Dict, List, Set

def validate_ocel_semantics(ocel: Dict) -> List[str]:
    """
    Valida las restricciones semánticas de OCEL 2.0 siguiendo el estándar JSON oficial.
    Verifica integridad referencial, tipos declarados y duplicados.
    """
    errors = []

    # Cargamos las colecciones principales (Estándar OCEL 2.0 oficial)
    events = ocel.get("events", [])
    objects = ocel.get("objects", [])
    event_types = {et["name"] for et in ocel.get("eventTypes", [])}
    object_types = {ot["name"] for ot in ocel.get("objectTypes", [])}

    # Inventarios para validación cruzada
    object_ids: Set[str] = set()
    event_ids: Set[str] = set()

    # Pasa 1: Inventario de IDs
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

    # Pasa 2: Validación de Referencias e Integridad
    
    # Validar Eventos
    for event in events:
        eid = event.get("id", "unknown")
        etype = event.get("type")

        # 2.1 Verificar si el tipo de evento fue declarado
        if etype and etype not in event_types:
            errors.append(f"Event {eid} uses undeclared eventType '{etype}'")

        # 2.2 Verificar relaciones Evento -> Objeto
        # Según estándar OCEL 2.0: {"objectId": "o1", "qualifier": "item"}
        for rel in event.get("relationships", []):
            target_id = rel.get("objectId")
            if not target_id:
                errors.append(f"Event {eid} has a relationship missing 'objectId'")
                continue

            if target_id not in object_ids:
                errors.append(f"Event {eid} references non-existent object: {target_id}")

    # Validar Objetos
    for obj in objects:
        oid = obj.get("id", "unknown")
        otype = obj.get("type")

        # 2.3 Verificar si el tipo de objeto fue declarado
        if otype and otype not in object_types:
            errors.append(f"Object {oid} uses undeclared objectType '{otype}'")

        # 2.4 Verificar Atributos de Objetos (Snapshots)
        # OCEL 2.0 exige 'time' en los atributos de los objetos
        for attr in obj.get("attributes", []):
            if "time" not in attr:
                errors.append(f"Object {oid}, attribute '{attr.get('name')}': Missing required 'time' field")

    # 2.5 Relaciones Objeto -> Objeto (Si existen en el log)
    # Nota: El estándar permite rel. O2O dentro de los objetos o en una colección aparte
    # Si las tienes en una colección raíz 'objectRelationships':
    for i, rel in enumerate(ocel.get("objectRelationships", [])):
        source = rel.get("sourceId")
        target = rel.get("targetId")
        if source and source not in object_ids:
            errors.append(f"Object Relationship {i}: Source '{source}' not found")
        if target and target not in object_ids:
            errors.append(f"Object Relationship {i}: Target '{target}' not found")

    return errors