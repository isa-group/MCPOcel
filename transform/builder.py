import uuid
import json
import logging
from typing import Dict, List, Optional, Any, Set, Union, Tuple, Sequence
from datetime import datetime
from pathlib import Path

# Logger local
logger = logging.getLogger(__name__)

# CONSTANTS
OCEL_GLOBAL_LOG = "ocel:global-log"
OCEL_GLOBAL_EVENT = "ocel:global-event"
OCEL_GLOBAL_OBJECT = "ocel:global-object"
OCEL_VERSION = "ocel:version"
OCEL_ORDERING = "ocel:ordering"
OCEL_ATTR_NAMES = "ocel:attribute-names"
OCEL_OBJ_TYPES = "ocel:object-types"
OCEL_EVT_TYPES = "ocel:event-types"
OCEL_OBJECTS = "ocel:objects"
OCEL_EVENTS = "ocel:events"

OCEL_TYPE = "ocel:type"
OCEL_NAME = "ocel:name"
OCEL_ACTIVITY = "ocel:activity"
OCEL_TIMESTAMP = "ocel:timestamp"
OCEL_OMAP = "ocel:omap"
OCEL_VMAP = "ocel:vmap"
OCEL_OVMAP = "ocel:ovmap"
OCEL_ATTRIBUTES = "ocel:attributes"

# SCHEMA DEFINITIONS
OBJECT_TYPES: Dict[str, List[str]] = {
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

ATTRIBUTE_TYPE_HINTS: Dict[str, Union[type, Tuple[type, ...]]] = {
    "number": int, "merged": bool, "duration_seconds": (int, float),
    "additions": int, "deletions": int, "files_changed": int,
    "state": str, "conclusion": str, "color": str, "name": str
}

TYPE_MAP = {str: "string", int: "integer", float: "float", bool: "boolean", datetime: "timestamp"}

class OCELBuilder:
    def __init__(self):
        self._global_attributes: Set[str] = set()
        for attrs in OBJECT_TYPES.values():
            self._global_attributes.update(attrs)

        self.ocel: Dict[str, Any] = {
            OCEL_GLOBAL_LOG: {}, OCEL_GLOBAL_EVENT: {}, OCEL_GLOBAL_OBJECT: {},
            OCEL_VERSION: "2.0", OCEL_ORDERING: "timestamp",
            OCEL_ATTR_NAMES: [], OCEL_OBJ_TYPES: [], OCEL_EVT_TYPES: [],
            OCEL_OBJECTS: {}, OCEL_EVENTS: {}
        }
        self._init_object_types()

    def _get_ocel_type_name(self, attr_name: str) -> str:
        hint = ATTRIBUTE_TYPE_HINTS.get(attr_name, str)
        base_type = hint[0] if isinstance(hint, tuple) else hint
        return TYPE_MAP.get(base_type, "string")

    def _init_object_types(self) -> None:
        for obj_type, attrs in sorted(OBJECT_TYPES.items()):
            self.ocel[OCEL_OBJ_TYPES].append({
                OCEL_TYPE: obj_type,
                OCEL_ATTRIBUTES: [
                    {OCEL_NAME: a, OCEL_TYPE: self._get_ocel_type_name(a)} 
                    for a in sorted(attrs)
                ]
            })

    @staticmethod
    def _validate_iso_timestamp(timestamp: str) -> None:
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"Invalid ISO 8601 timestamp: {timestamp}")

    def _validate_attribute_types(self, attributes: Dict[str, Any]) -> None:
        for key, value in attributes.items():
            if key in ATTRIBUTE_TYPE_HINTS:
                expected = ATTRIBUTE_TYPE_HINTS[key]
                if not isinstance(value, expected):
                    logger.warning(
                        "Type mismatch for '%s': expected %s, got %s",
                        key, expected, type(value).__name__
                    )


    def add_object(self, obj_id: str, obj_type: str, attributes: Dict[str, Any]) -> None:
        if obj_type not in OBJECT_TYPES:
            raise ValueError(f"Unknown object type: {obj_type}")

        allowed = set(OBJECT_TYPES[obj_type])
        valid_attrs = {k: v for k, v in attributes.items() if k in allowed}
        if len(valid_attrs) < len(attributes):
            logger.warning(
                "Ignored extra attributes for %s %s",
                obj_type, obj_id
            )
        self._validate_attribute_types(valid_attrs)

        if obj_id not in self.ocel[OCEL_OBJECTS]:
            self.ocel[OCEL_OBJECTS][obj_id] = {OCEL_TYPE: obj_type, OCEL_OVMAP: valid_attrs}

    def _register_event_type_attributes(self, activity: str, new_attrs: Sequence[str]) -> None:
        self._global_attributes.update(new_attrs)
        target_et = next((et for et in self.ocel[OCEL_EVT_TYPES] if et[OCEL_TYPE] == activity), None)

        if not target_et:
            target_et = {OCEL_TYPE: activity, OCEL_ATTRIBUTES: []}
            self.ocel[OCEL_EVT_TYPES].append(target_et)

        existing = {a[OCEL_NAME] for a in target_et[OCEL_ATTRIBUTES]}
        for attr in new_attrs:
            if attr not in existing:
                target_et[OCEL_ATTRIBUTES].append({
                    OCEL_NAME: attr, 
                    OCEL_TYPE: self._get_ocel_type_name(attr)
                })

    def add_event(self, activity: str, timestamp: str, related_objects: Sequence[str], attributes: Optional[Dict[str, Any]] = None) -> str:
        self._validate_iso_timestamp(timestamp)
        missing = [oid for oid in related_objects if oid not in self.ocel[OCEL_OBJECTS]]
        if missing:
            raise ValueError(f"Event references unknown objects: {missing}")

        event_id = str(uuid.uuid4())
        event_attrs = attributes or {}
        self._validate_attribute_types(event_attrs)
        self._register_event_type_attributes(activity, list(event_attrs.keys()))

        self.ocel[OCEL_EVENTS][event_id] = {
            OCEL_ACTIVITY: activity, OCEL_TIMESTAMP: timestamp,
            OCEL_OMAP: related_objects, OCEL_VMAP: event_attrs
        }
        return event_id

    def export_json(self, filename: Union[str, Path], pretty: bool = True) -> None:
        # Finalize Attribute Names con Formato OCEL 2.0
        self.ocel[OCEL_ATTR_NAMES] = [
            {OCEL_NAME: n, OCEL_TYPE: self._get_ocel_type_name(n)}
            for n in sorted(self._global_attributes)
        ]

        # Deterministic Sort
        sorted_events = dict(sorted(self.ocel[OCEL_EVENTS].items(), 
                                    key=lambda x: (x[1][OCEL_TIMESTAMP], x[0])))
        self.ocel[OCEL_EVENTS] = sorted_events

        output_path = Path(filename)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.ocel, f, indent=2 if pretty else None, ensure_ascii=False)
        logger.info(f"Export complete: {output_path}")