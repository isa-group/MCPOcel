import uuid
import json
import logging
from typing import Dict, List, Optional, Any, Set, Union, Tuple, Sequence
from datetime import datetime
from pathlib import Path

# Logger local
logger = logging.getLogger(__name__)

# Schema Keys
ATTR_TYPES = "attributeNames"
EVT_TYPES = "eventTypes"
OBJ_TYPES_KEY = "objectTypes"
OBJECTS = "objects"
EVENTS = "events"

# Schema Constants
OBJECT_SCHEMA_DEFS: Dict[str, List[str]] = {
    "Repository": ["name", "full_name", "visibility"],
    "Issue": ["number", "state", "title", "created_at", "closed_at"],
    "PullRequest": ["number", "merged", "merged_at", "source"],
    "Commit": ["sha", "message", "source"],
    "WorkflowRun": ["run_id", "name", "conclusion", "duration_seconds"],
    "User": ["login"],
    "Branch": ["name"],
    "File": ["path"],
    "Label": ["name", "color"],
    "Release": ["tag_name", "name", "prerelease"]
}

# Attribute Type Hints
TYPE_MAP = {str: "string", int: "string", float: "string", bool: "string", datetime: "string"}

class OCELBuilder:
    def __init__(self):
        self.data = {
            EVT_TYPES: [],
            OBJ_TYPES_KEY: [],
            OBJECTS: {},
            EVENTS: []
        }
        self._global_attributes: Set[str] = set()
        self._init_object_types()

    def _get_type_name(self, value: Any) -> str:
        return TYPE_MAP.get(type(value), "string")

    def _init_object_types(self) -> None:
        # Object Types Initialization
        for obj_type, attrs in sorted(OBJECT_SCHEMA_DEFS.items()):
            self.data[OBJ_TYPES_KEY].append({
                "name": obj_type,
                "attributes": [{"name": a, "type": "string"} for a in sorted(attrs)]
            })

    def add_object(self, obj_id: str, obj_type: str, attributes: Dict[str, Any]) -> None:
        if obj_id in self.data[OBJECTS]:
            return

        # Atributes Formatting
        now_iso = datetime.now().isoformat() + "Z"
        formatted_attrs = []
        for k, v in attributes.items():
            formatted_attrs.append({
                "name": k,
                "value": str(v),
                "time": now_iso
            })

        self.data[OBJECTS][obj_id] = {
            "id": obj_id,
            "type": obj_type,
            "attributes": formatted_attrs,
            "relationships": [] # Opcional
        }

    def _register_event_type(self, activity: str, attributes: Dict[str, Any]) -> None:
        # EVT_TYPES Registration
        target = next((et for et in self.data[EVT_TYPES] if et["name"] == activity), None)
        if not target:
            target = {"name": activity, "attributes": []}
            self.data[EVT_TYPES].append(target)

        existing_attrs = {a["name"] for a in target["attributes"]}
        for k, v in attributes.items():
            if k not in existing_attrs:
                target["attributes"].append({"name": k, "type": "string"})

    def add_event(self, activity: str, timestamp: str, related_objects: Sequence[str], 
                  attributes: Optional[Dict[str, Any]] = None) -> str:
        # Generate unique event ID
        event_id = str(uuid.uuid4())
        event_attrs = attributes or {}

        # Event Type Registration
        self._register_event_type(activity, event_attrs)

        # Event Formatting
        formatted_attrs = [{"name": k, "value": str(v)} for k, v in event_attrs.items()]

        # Relationships Formatting
        relationships = [{"objectId": oid, "qualifier": "related"} for oid in related_objects]

        self.data[EVENTS].append({
            "id": event_id,
            "type": activity,
            "time": timestamp if "Z" in timestamp else f"{timestamp}Z",
            "attributes": formatted_attrs,
            "relationships": relationships
        })
        return event_id

    def export_json(self, filename: Union[str, Path], pretty: bool = True) -> None:
        # Export OCEL JSON
        final_output = {
            "eventTypes": self.data[EVT_TYPES],
            "objectTypes": self.data[OBJ_TYPES_KEY],
            "events": self.data[EVENTS],
            "objects": list(self.data[OBJECTS].values())
        }

        # Order events by timestamp
        final_output["events"].sort(key=lambda x: x["time"])

        output_path = Path(filename)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(final_output, f, indent=2 if pretty else None, ensure_ascii=False)

        logger.info(f"Export complete: {output_path}")