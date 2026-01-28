import uuid
import json
import logging
from typing import Dict, List, Optional, Any, Union, Tuple, Sequence
from datetime import datetime
from pathlib import Path

# Local logger
logger = logging.getLogger(__name__)

# SCHEMA KEYS (Matching your JSON Schema)
EVT_TYPES = "eventTypes"
OBJ_TYPES_KEY = "objectTypes"
OBJECTS = "objects"
EVENTS = "events"

# SCHEMA DEFINITIONS
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

# Type validation hints
ATTRIBUTE_TYPE_HINTS: Dict[str, Union[type, Tuple[type, ...]]] = {
    "number": int, "merged": bool, "duration_seconds": (int, float),
    "additions": int, "deletions": int, "files_changed": int,
    "state": str, "conclusion": str, "color": str, "name": str
}

class OCELBuilder:
    """
    OCEL Builder aligned with custom JSON Schema.
    Ensures type safety, referential integrity, and deterministic export.
    """
    def __init__(self):
        self.data = {
            EVT_TYPES: [],
            OBJ_TYPES_KEY: [],
            OBJECTS: {},
            EVENTS: []
        }
        self._init_object_types()

    def _init_object_types(self) -> None:
        """Initialize static object types based on definitions."""
        for obj_type, attrs in sorted(OBJECT_SCHEMA_DEFS.items()):
            self.data[OBJ_TYPES_KEY].append({
                "name": obj_type,
                "attributes": [{"name": a, "type": "string"} for a in sorted(attrs)]
            })

    def _validate_attribute_types(self, attributes: Dict[str, Any]) -> None:
        """Log warnings if attribute types do not match expectations."""
        for key, value in attributes.items():
            if key in ATTRIBUTE_TYPE_HINTS:
                expected = ATTRIBUTE_TYPE_HINTS[key]
                if not isinstance(value, expected):
                    # Format expected type name for clarity
                    if isinstance(expected, tuple):
                        expected_name = ", ".join(t.__name__ for t in expected)
                    else:
                        expected_name = getattr(expected, "__name__", str(expected))

                    logger.warning(
                        "Type mismatch for '%s': expected %s, got %s (Value: %s)",
                        key, expected_name, type(value).__name__, value
                    )

    def add_object(self, obj_id: str, obj_type: str, attributes: Dict[str, Any]) -> None:
        """Adds a unique object to the log."""
        if obj_id in self.data[OBJECTS]:
            return

        self._validate_attribute_types(attributes)

        now_iso = datetime.now().isoformat() + "Z"
        formatted_attrs = [
            {"name": k, "value": str(v), "time": now_iso}
            for k, v in attributes.items()
        ]

        self.data[OBJECTS][obj_id] = {
            "id": obj_id,
            "type": obj_type,
            "attributes": formatted_attrs,
            "relationships": []
        }

    def _register_event_type(self, activity: str, attributes: Dict[str, Any]) -> None:
        """Registers event attributes dynamically in the schema header."""
        target = next((et for et in self.data[EVT_TYPES] if et["name"] == activity), None)
        if not target:
            target = {"name": activity, "attributes": []}
            self.data[EVT_TYPES].append(target)

        existing_attrs = {a["name"] for a in target["attributes"]}
        for k in attributes.keys():
            if k not in existing_attrs:
                target["attributes"].append({"name": k, "type": "string"})

    def add_event(self, activity: str, timestamp: str, related_objects: Sequence[str],
                  attributes: Optional[Dict[str, Any]] = None) -> str:
        """Adds an event and links it to objects. Returns the event UUID."""
        event_id = str(uuid.uuid4())
        event_attrs = attributes or {}

        self._validate_attribute_types(event_attrs)
        self._register_event_type(activity, event_attrs)

        formatted_attrs = [{"name": k, "value": str(v)} for k, v in event_attrs.items()]

        # Ensure relationships follow the (objectId, qualifier) schema
        relationships = [
            {"objectId": str(oid), "qualifier": "related"}
            for oid in list(related_objects)
        ]

        self.data[EVENTS].append({
            "id": event_id,
            "type": activity,
            "time": timestamp if "Z" in timestamp else f"{timestamp}Z",
            "attributes": formatted_attrs,
            "relationships": relationships
        })
        return event_id

    def export_json(self, filename: Union[str, Path], pretty: bool = True) -> None:
        """Finalizes the OCEL structure and writes it to a JSON file."""

        # Build final dictionary using defined constants
        final_output = {
            EVT_TYPES: self.data[EVT_TYPES],
            OBJ_TYPES_KEY: self.data[OBJ_TYPES_KEY],
            EVENTS: self.data[EVENTS],
            OBJECTS: list(self.data[OBJECTS].values())
        }

        # Deterministic sort: Primary by time, Secondary by ID to break ties
        final_output[EVENTS].sort(key=lambda x: (x["time"], x["id"]))

        output_path = Path(filename)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(final_output, f, indent=2 if pretty else None, ensure_ascii=False)

        logger.info(f"Export successful. {len(final_output[EVENTS])} events saved to: {output_path}")
