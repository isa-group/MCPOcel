import uuid
import json
import logging
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

class OCELBuilder:
    """
    OCEL 2.0 Builder that generates standard-compliant files.
    Compatible with existing mappers using rel() method.
    """

    def __init__(self):
        self.data = {
            "ocel:global-log": {
                "ocel:version": "2.0",
                "ocel:ordering": "timestamp",
                "ocel:attribute-names": []
            },
            "ocel:global-event": {},              # event_type -> attributes
            "ocel:global-object": {},             # object_type -> attributes
            "ocel:events": {},                    # event_id -> event
            "ocel:objects": {},                   # object_id -> object
            "ocel:object-relationships": []       # object_relationships -> object
        }
        self._all_attributes = set()

    def rel(self, object_id: str, qualifier: str) -> Dict[str, str]:
        """
        Helper for creating relationships.
        Maintains compatibility with existing mappers.
        """
        safe_id = str(object_id).strip()
        return {"objectId": str(safe_id), "qualifier": str(qualifier)}

    def _get_ocel_type(self, value: Any) -> str:
        """Infer OCEL type from Python value."""
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "string"
        return "string"

    def _register_attribute(self, attr_name: str):
        """Track all attribute names for global-log."""
        self._all_attributes.add(attr_name)

    def _register_event_type(self, activity: str, attributes: Dict[str, Any]):
        """Register event type in global-event metadata."""
        if activity not in self.data["ocel:global-event"]:
            self.data["ocel:global-event"][activity] = []

        existing_attrs = {
            a["ocel:name"] 
            for a in self.data["ocel:global-event"][activity]
        }

        for attr_name, value in attributes.items():
            self._register_attribute(attr_name)

            if attr_name not in existing_attrs:
                self.data["ocel:global-event"][activity].append({
                    "ocel:name": attr_name,
                    "ocel:type": self._get_ocel_type(value)
                })

    def _register_object_type(self, obj_type: str, attributes: Dict[str, Any]):
        """Register object type in global-object metadata."""
        if obj_type not in self.data["ocel:global-object"]:
            self.data["ocel:global-object"][obj_type] = []

        existing_attrs = {
            a["ocel:name"]
            for a in self.data["ocel:global-object"][obj_type]
        }

        for attr_name, value in attributes.items():
            self._register_attribute(attr_name)

            if attr_name not in existing_attrs:
                self.data["ocel:global-object"][obj_type].append({
                    "ocel:name": attr_name,
                    "ocel:type": self._get_ocel_type(value)
                })

    def add_object(self, obj_id: str, obj_type: str, attributes: Dict[str, Any]):
        """
        Add or update an object with temporal attribute tracking.

        Args:
            obj_id: Unique object identifier
            obj_type: Object type (e.g., "Issue", "Commit")
            attributes: Dictionary of attribute name -> value
        """
        self._register_object_type(obj_type, attributes)

        # Get current timestamp
        now_iso = datetime.now().isoformat()
        if not now_iso.endswith("Z"):
            now_iso += "Z"


        # Create or update object
        if obj_id not in self.data["ocel:objects"]:
            self.data["ocel:objects"][obj_id] = {
                "ocel:oid": obj_id,
                "ocel:type": obj_type,
                "ocel:ovmap": {}
            }

        obj = self.data["ocel:objects"][obj_id]

        # Add attributes with timestamp
        for key, value in attributes.items():
            if key not in obj["ocel:ovmap"]:
                obj["ocel:ovmap"][key] = []
            """
            # Check if this exact value already exists (avoid duplicates)
            existing_values = [
                entry["ocel:value"]
                for entry in obj["ocel:ovmap"][key]
            ]

            if value not in existing_values:
                obj["ocel:ovmap"][key].append({
                    "ocel:time": now_iso,
                    "ocel:value": value
                })
            """
            # 2. Evitar redundancia: Solo registrar si el valor cambia
            last_entry = obj["ocel:ovmap"][key][-1] if obj["ocel:ovmap"][key] else None
            if last_entry is None or last_entry["ocel:value"] != value:
                obj["ocel:ovmap"][key].append({
                    "ocel:time": now_iso,
                    "ocel:value": value
                })

    def add_event(
        self,
        activity: str,
        timestamp: str,
        relationships: List[Dict[str, str]],
        attributes: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Add an event to the OCEL log.

        Args:
            activity: Event activity/type (e.g., "IssueOpened")
            timestamp: ISO 8601 timestamp
            relationships: List of {objectId, qualifier} dicts
            attributes: Optional event attributes

        Returns:
            Generated event ID
        """
        event_id = str(uuid.uuid4())
        event_attrs = attributes or {}

        self._register_event_type(activity, event_attrs)

        # Normalize timestamp
        if not timestamp.endswith("Z"):
            timestamp = f"{timestamp}Z"

        # Build ocel:omap (list of object IDs)
        omap = []
        vmap = dict(event_attrs)

        for rel in relationships:
            obj_id = rel["objectId"]
            qualifier = rel["qualifier"]

            # Add to omap (avoiding duplicates)
            if obj_id not in omap:
                omap.append(obj_id)

            # Store qualifier as special attribute
            # This preserves semantic information in OCEL 2.0
            qualifier_key = f"ocel:qualifier:{obj_id}"
            vmap[qualifier_key] = qualifier

        # Create event
        self.data["ocel:events"][event_id] = {
            "ocel:eid": event_id,
            "ocel:activity": activity,
            "ocel:timestamp": timestamp,
            "ocel:omap": omap,
            "ocel:vmap": vmap
        }

        return event_id

    def add_object_relationship(self, source_id: str, target_id: str, qualifier: str):
        """Establece un vínculo directo entre dos objetos (OCEL 2.0 Standard)"""
        self.data["ocel:object-relationships"].append({
            "ocel:sourceId": str(source_id),
            "ocel:targetId": str(target_id),
            "ocel:qualifier": str(qualifier)
        })

    def export_json(self, filename: Union[str, Path], pretty: bool = True):
        """
        Export OCEL 2.0 file.

        Args:
            filename: Output file path
            pretty: Whether to format with indentation
        """
        output_path = Path(filename)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Update global attribute names
        self.data["ocel:global-log"]["ocel:attribute-names"] = sorted(
            list(self._all_attributes)
        )

        # Build final structure with lists instead of dicts
        final_data = {
            "ocel:global-log": self.data["ocel:global-log"],
            "ocel:global-event": self.data["ocel:global-event"],
            "ocel:global-object": self.data["ocel:global-object"],
            "ocel:events": list(self.data["ocel:events"].values()),
            "ocel:objects": list(self.data["ocel:objects"].values()),
            "ocel:object-relationships": self.data.get("ocel:object-relationships", [])
        }

        # Sort events by timestamp
        final_data["ocel:events"].sort(
            key=lambda e: (e["ocel:timestamp"], e["ocel:eid"])
        )

        # Write to file
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(final_data, f, indent=2 if pretty else None, ensure_ascii=False)

        logger.info(
            f"OCEL 2.0 exported: {len(final_data['ocel:events'])} events, "
            f"{len(final_data['ocel:objects'])} objects → {output_path}"
        )

    def get_stats(self) -> Dict[str, int]:
        """Get current statistics."""
        return {
            "objects": len(self.data["ocel:objects"]),
            "events": len(self.data["ocel:events"]),
            "event_types": len(self.data["ocel:global-event"]),
            "object_types": len(self.data["ocel:global-object"])
        }
