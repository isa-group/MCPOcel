from typing import Dict, List, Any, Optional
from github2ocel.transform.utils.helper import to_iso8601

class EventType:
    def __init__(self, name: str, attributes: Dict[str, str] = None):
        self.name = name
        self.attributes = attributes  # {attr_name: attr_type}


class ObjectType:
    def __init__(self, name: str, attributes: Dict[str, str] = None):
        self.name = name
        self.attributes = attributes  # {attr_name: attr_type}


class Event:
    def __init__(
        self,
        event_id: str,
        event_type: str,
        time: Any,
        attributes: Dict[str, Any] = None
        ):
            self.id = event_id
            self.type = event_type
            self.time = to_iso8601(time)
            self.attributes = attributes or {}
            self.relationships = []  # (object_id, qualifier)

    def add_rel(self, object_id: str, qualifier: str = None):
        """Helper for quickly adding relationships"""
        if qualifier is None:
            qualifier = "relates_to"
        self.relationships.append((object_id, qualifier))


class ObjectSnapshot:
    def __init__(
        self,
        time: Any,
        attributes: Dict[str, Any],
        changed_field: str = None):
            self.time = to_iso8601(time)
            self.changed_field = changed_field
            self.attributes = attributes


class ObjectInstance:
    def __init__(self, object_id: str, object_type: str):
        self.id = object_id
        self.type = object_type
        self.snapshots: List[ObjectSnapshot] = []
        self.related_objects: List[tuple[str, str]] = []

    def add_snapshot(self, time: Any, attributes: Dict[str, Any]):
        self.snapshots.append(ObjectSnapshot(time, attributes))

    def add_rel(self, target_id: str, qualifier: str = None):
        if qualifier is None:
            qualifier = "relates_to"

        self.related_objects.append((target_id, qualifier))