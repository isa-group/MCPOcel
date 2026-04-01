import sqlite3
import json
import logging
from pathlib import Path
from typing import Dict, Any, List
from collections import defaultdict

logger = logging.getLogger(__name__)


class OCEL2JsonExporter:
    """
    Exports an OCEL 2.0 SQLite database to a standard OCEL 2.0 JSON file.
    Handles the transformation from relational (flat) to hierarchical (nested) format.

      1. changed_field: each attribute entry uses ocel_changed_field as its semantic
         key — RESERVED_FULL_UPDATE rows are treated as full-state snapshots and
         emit all their attributes with that row's timestamp.
      2. Object attribute sort: rows are sorted by ocel_time ASC so the attribute
         history reflects chronological state changes.
      3. objectRelationships: uses objectId / relatedObjectId per the OCEL 2.0 spec.
      4. table_map: removed from eventTypes / objectTypes output — internal detail only.
    """
    def __init__(self, db_path: Path):
        self.db_path = db_path
        # Connect in read-only mode just in case
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row  # Allows accessing columns by name
        self.cursor = self.conn.cursor()

    def export(self, output_path: Path):
        logger.info(f"Starting JSON export from {self.db_path}...")

        # Standard root structure of OCEL 2.0
        ocel_data = {
            "eventTypes": [],
            "objectTypes": [],
            "events": [],
            "objects": [],
        }

        try:
            # Schema
            logger.info("Building Types Schema...")
            ocel_data["eventTypes"] = self._build_types("event")
            ocel_data["objectTypes"] = self._build_types("object")

            # Load Relationships into Memory
            logger.info("Loading relationships map...")
            e2o_map = self._load_relationships("event_object", "ocel_event_id", "ocel_object_id")

            # Data (Events and Objects)
            logger.info("Exporting Events...")
            ocel_data["events"] = self._export_events(ocel_data["eventTypes"], e2o_map)

            logger.info("Exporting Objects...")
            ocel_data["objects"] = self._export_objects(ocel_data["objectTypes"])


            # Write file
            logger.info(f"Writing JSON file to {output_path}...")
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(ocel_data, f, indent=2)

            logger.info("JSON Export completed successfully.")

        finally:
            self.conn.close()

    def _get_json_type(self, sql_type: str) -> str:
        """Maps SQLite types to OCEL 2.0 JSON types."""
        sql_type = sql_type.upper()
        if "INT" in sql_type: return "integer"
        if "REAL" in sql_type or "FLOAT" in sql_type: return "float"
        if "BOOL" in sql_type: return "boolean"
        return "string"

    def _build_types(self, kind: str) -> List[Dict[str, Any]]:
        """
        Build type definitions from the map tables and table schemas.
        Only emits 'name' and 'attributes' — no internal 'table_map' field.
        """
        types_list = []
        map_table  = f"{kind}_map_type"

        rows = self.cursor.execute(
            f"SELECT ocel_type, ocel_type_map FROM {map_table}"
        ).fetchall()

        for row in rows:
            type_name  = row["ocel_type"]
            table_name = f"{kind}_{row['ocel_type_map']}"

            columns = self.cursor.execute(
                f"PRAGMA table_info({table_name})"
            ).fetchall()

            attributes = []
            for col in columns:
                col_name = col["name"]
                if col_name in ("ocel_id", "ocel_time", "ocel_changed_field"):
                    continue
                attributes.append({
                    "name": col_name,
                    "type": self._get_json_type(col["type"]),
                })

            # Fix 4: only standard OCEL 2.0 fields — no table_map
            types_list.append({
                "name":       type_name,
                "attributes": attributes,
            })

        return types_list

    def _load_relationships(
        self, table: str, source_col: str, target_col: str
    ) -> Dict[str, List[Dict]]:
        """Load event→object relations into {source_id: [{objectId, qualifier}]}."""
        rels = defaultdict(list)
        rows = self.cursor.execute(
            f"SELECT {source_col}, {target_col}, ocel_qualifier FROM {table}"
        ).fetchall()
        for row in rows:
            rels[row[source_col]].append({
                "objectId":  row[target_col],
                "qualifier": row["ocel_qualifier"],
            })
        return rels

    # Exporters
    def _export_events(
        self, event_types: List[Dict], rel_map: Dict
    ) -> List[Dict]:
        events = []

        for et in event_types:
            type_name = et["name"]
            map_row   = self.cursor.execute(
                "SELECT ocel_type_map FROM event_map_type WHERE ocel_type = ?",
                (type_name,)
            ).fetchone()
            table_name = f"event_{map_row['ocel_type_map']}"
            attr_names = [a["name"] for a in et["attributes"]]

            # Massive select
            rows = self.cursor.execute(f'SELECT * FROM "{table_name}"').fetchall()
            for row in rows:
                ev = {
                    "id": row["ocel_id"],
                    "type": type_name,
                    "time": row["ocel_time"],
                    "attributes": [],
                    "relationships": rel_map.get(row["ocel_id"], []),
                }

                # Map flat attributes to list of dictionaries
                for name in attr_names:
                    if row[name] is not None:
                        ev["attributes"].append({
                            "name":  name,
                            "value": row[name],
                        })
                events.append(ev)

        # Sort by time - required for process mining tools
        events.sort(key=lambda x: x["time"])
        return events

    def _export_objects(self, object_types: List[Dict]) -> List[Dict]:
        """
        Exports objects strictly following the OCEL 2.0 JSON schema.

        1. 'Ghost Objects': Initializes all objects from the base table first.
        2. 'O2O Relationships': Embedded inside the object's 'relationships' array.
        3. 'Race Conditions': Uses rowid for deterministic sorting.
        4. 'Boolean Casting': Restores True/False from SQLite's 1/0.
        """
        objects_dict: Dict[str, Dict] = {}

        # 1. PRE-LOAD: Initialize all objects from the base table
        # This prevents dropping objects that have no attributes/snapshots yet.
        base_rows = self.cursor.execute("SELECT ocel_id, ocel_type FROM object").fetchall()
        for row in base_rows:
            objects_dict[row["ocel_id"]] = {
                "id": row["ocel_id"],
                "type": row["ocel_type"],
                "attributes": [],
                "relationships": []  # O2O relationships go here in OCEL 2.0 JSON
            }

        # 2. O2O RELATIONSHIPS: Load and attach to their source objects
        o2o_rows = self.cursor.execute(
            "SELECT ocel_source_id, ocel_target_id, ocel_qualifier FROM object_object"
        ).fetchall()

        for row in o2o_rows:
            source_id = row["ocel_source_id"]
            if source_id in objects_dict:
                objects_dict[source_id]["relationships"].append({
                    "objectId": row["ocel_target_id"],
                    "qualifier": row["ocel_qualifier"]
                })

        # 3. ATTRIBUTES: Process snapshots dynamically
        for ot in object_types:
            type_name = ot["name"]

            # Identify boolean attributes for this type to cast them back from 0/1
            bool_attrs = {a["name"] for a in ot["attributes"] if a["type"] == "boolean"}
            attr_names = [a["name"] for a in ot["attributes"]]

            map_row = self.cursor.execute(
                "SELECT ocel_type_map FROM object_map_type WHERE ocel_type = ?",
                (type_name,)
            ).fetchone()

            if not map_row:
                continue # Type is registered but no table was ever created

            table_name = f"object_{map_row['ocel_type_map']}"

            try:
                # Explicit chronological sort with 'rowid' as tie-breaker for race conditions
                rows = self.cursor.execute(
                    f'SELECT *, rowid FROM "{table_name}" ORDER BY ocel_time ASC, rowid ASC'
                ).fetchall()
            except sqlite3.OperationalError:
                continue # Table doesn't exist yet in SQLite

            for row in rows:
                oid = row["ocel_id"]
                ts  = row["ocel_time"]
                changed_field = row["ocel_changed_field"]

                # Safety net (should already be loaded from base table)
                if oid not in objects_dict:
                    objects_dict[oid] = {
                        "id": oid,
                        "type": type_name,
                        "attributes": [],
                        "relationships": []
                    }

                is_full_update = (
                    changed_field is None
                    or changed_field == "RESERVED_FULL_UPDATE"
                )

                for name in attr_names:
                    val = row[name]
                    if val is None:
                        continue

                    if not is_full_update and name != changed_field:
                        continue

                    # Reverse boolean casting: SQLite INTEGER (1/0) -> JSON BOOLEAN (True/False)
                    if name in bool_attrs:
                        val = bool(val)

                    objects_dict[oid]["attributes"].append({
                        "name":  name,
                        "time":  ts,
                        "value": val,
                    })

        return list(objects_dict.values())

    def _export_o2o(self) -> List[Dict]:
        """
        Uses objectId / relatedObjectId per the OCEL 2.0 JSON schema.
        (Previous implementation used non-standard sourceId / targetId.)
        """
        o2o_list = []
        rows = self.cursor.execute(
            "SELECT ocel_source_id, ocel_target_id, ocel_qualifier FROM object_object"
        ).fetchall()
        for row in rows:
            o2o_list.append({
                "objectId": row["ocel_source_id"],
                "relatedObjectId": row["ocel_target_id"],
                "qualifier": row["ocel_qualifier"],
            })
        return o2o_list