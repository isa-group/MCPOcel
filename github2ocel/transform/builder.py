import sqlite3
import json
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Union

logger = logging.getLogger(__name__)

class OCELBuilder:
    """
    OCEL 2.0 Builder optimised for large volumes of data with persistence in SQLite.
    Includes batch handling, optional logging, and streaming export.
    """
    def __init__(self, db_path: Optional[Union[str, Path]] = None, log_level: int = logging.INFO):
        self.db_path = Path(db_path) if db_path else Path("ocel_staging.db")
        if self.db_path.exists():
            self.db_path.unlink()

        self.conn = sqlite3.connect(str(self.db_path))
        self._setup_db()
        self._all_attributes = set()
        self.log_level = log_level
        logging.basicConfig(level=log_level, format='[%(levelname)s] %(message)s')
        logger.debug(f"SQLiteOCELBuilder initialized at {self.db_path}")

    # Context manager
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.conn.rollback()
            logger.error(f"Exception occurred: {exc_val}. Rolled back transaction.")
        self.close()

    # Setup DB
    def _setup_db(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE objects (
                oid TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                ovmap_json TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE events (
                eid TEXT PRIMARY KEY,
                activity TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                vmap_json TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX idx_event_time ON events(timestamp)")
        cursor.execute("""
            CREATE TABLE event_object_map (
                eid TEXT,
                oid TEXT,
                qualifier TEXT,
                FOREIGN KEY(eid) REFERENCES events(eid),
                FOREIGN KEY(oid) REFERENCES objects(oid)
            )
        """)
        cursor.execute("""
            CREATE TABLE object_relationships (
                source_id TEXT,
                target_id TEXT,
                qualifier TEXT
            )
        """)
        cursor.execute("CREATE INDEX idx_objects_type ON objects(type)")
        cursor.execute("CREATE INDEX idx_events_activity ON events(activity)")
        cursor.execute("CREATE INDEX idx_eom_eid ON event_object_map(eid)")
        cursor.execute("CREATE INDEX idx_eom_oid ON event_object_map(oid)")
        cursor.execute("CREATE INDEX idx_rel_source ON object_relationships(source_id)")
        cursor.execute("CREATE INDEX idx_rel_target ON object_relationships(target_id)")

        self.conn.commit()
        logger.debug("Database schema initialized")

    # Helpers
    @staticmethod
    def _normalize_timestamp(ts: str) -> str:
        """Normalises any ISO8601 to UTC-Z"""
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception as e:
            logger.warning(f"Invalid timestamp {ts}, using current UTC: {e}")
            return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def rel(object_id: str, qualifier: str) -> Dict[str, str]:
        return {"objectId": str(object_id), "qualifier": str(qualifier)}


    # Core methods
    def add_object(self, obj_id: str, obj_type: str, attributes: Dict[str, Any]):
        """Insert or update an object with versioned OVMap, implicit batch commit"""
        now_iso = self._normalize_timestamp(datetime.now(timezone.utc).isoformat())
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT ovmap_json FROM objects WHERE oid = ?", (obj_id,))
            row = cursor.fetchone()
            ovmap = json.loads(row[0]) if row else {}

            for key, value in attributes.items():
                self._all_attributes.add(key)
                if key not in ovmap:
                    ovmap[key] = []
                if not ovmap[key] or ovmap[key][-1]["ocel:value"] != value:
                    ovmap[key].append({"ocel:time": now_iso, "ocel:value": value})

            cursor.execute("""
                INSERT OR REPLACE INTO objects (oid, type, ovmap_json)
                VALUES (?, ?, ?)
            """, (obj_id, obj_type, json.dumps(ovmap)))
            if self.log_level <= logging.DEBUG:
                logger.debug(f"Object added: {obj_id}")

    def add_object_relationship(self, source_id: str, target_id: str, qualifier: str):
        with self.conn:
            self.conn.execute("""
                INSERT INTO object_relationships (source_id, target_id, qualifier)
                VALUES (?, ?, ?)
            """, (source_id, target_id, qualifier))
            if self.log_level <= logging.DEBUG:
                logger.debug(f"Relationship added: {source_id} -[{qualifier}]-> {target_id}")

    def add_event(self, activity: str, timestamp: str,
                  relationships: List[Dict[str, str]],
                  attributes: Optional[Dict[str, Any]] = None) -> str:
        """Record an event and relationships, implicit batch commit"""
        event_id = str(uuid.uuid4())
        vmap = attributes.copy() if attributes else {}
        ts = self._normalize_timestamp(timestamp)

        with self.conn:
            for rel in relationships:
                oid = rel["objectId"]
                qual = rel["qualifier"]
                vmap[f"ocel:qualifier:{oid}"] = qual
                self.conn.execute("""
                    INSERT INTO event_object_map (eid, oid, qualifier)
                    VALUES (?, ?, ?)
                """, (event_id, oid, qual))

            self.conn.execute("""
                INSERT INTO events (eid, activity, timestamp, vmap_json)
                VALUES (?, ?, ?, ?)
            """, (event_id, activity, ts, json.dumps(vmap)))
            if self.log_level <= logging.DEBUG:
                logger.debug(f"Event added: {event_id} - {activity} at {ts}")
        return event_id

    # Stats
    def get_stats(self) -> Dict[str, int]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM events")
        ev_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM objects")
        obj_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM object_relationships")
        rel_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM event_object_map")
        evobj_count = cursor.fetchone()[0]
        return {
            "events": ev_count,
            "objects": obj_count,
            "relationships": rel_count,
            "event_object_links": evobj_count
        }

    def get_object(self, oid: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT type, ovmap_json FROM objects WHERE oid = ?", (oid,))
        row = cursor.fetchone()
        if row:
            obj_type, ovmap_json = row
            return {"oid": oid, "type": obj_type, "ovmap": json.loads(ovmap_json)}
        return None


    # Export
    def export_json(self, filename: Union[str, Path]):
        """Complete streaming export: log, events, objects, and relationships."""
        with open(filename, "w", encoding="utf-8") as f:
            # 1. Metadata
            f.write('{\n  "ocel:global-log": {\n')
            f.write('    "ocel:version": "2.0",\n')
            f.write('    "ocel:ordering": "timestamp",\n')
            f.write(f'    "ocel:attribute-names": {json.dumps(sorted(list(self._all_attributes)))}\n')
            f.write('  },\n')

            # 2. Global Event & Object (Catálogo de tipos)
            global_events = {row[0]: [] for row in self.conn.execute("SELECT DISTINCT activity FROM events")}
            f.write(f'  "ocel:global-event": {json.dumps(global_events, indent=2)},\n')

            global_objects = {row[0]: [] for row in self.conn.execute("SELECT DISTINCT type FROM objects")}
            f.write(f'  "ocel:global-object": {json.dumps(global_objects, indent=2)},\n')

            # 3. Events (Streaming)
            f.write('  "ocel:events": [\n')
            cursor = self.conn.execute("SELECT eid, activity, timestamp, vmap_json FROM events ORDER BY timestamp ASC")
            first = True
            for eid, activity, ts, vmap_json in cursor:
                if not first: f.write(',\n')
                rel_cursor = self.conn.execute("SELECT oid FROM event_object_map WHERE eid = ?", (eid,))
                omap = [r[0] for r in rel_cursor]
                event_dict = {
                    "ocel:eid": eid, "ocel:activity": activity,
                    "ocel:timestamp": ts, "ocel:omap": omap,
                    "ocel:vmap": json.loads(vmap_json)
                }
                f.write(f"    {json.dumps(event_dict)}")
                first = False
            f.write('\n  ],\n')

            # 4. Objects (Streaming)
            f.write('  "ocel:objects": [\n')
            cursor = self.conn.execute("SELECT oid, type, ovmap_json FROM objects")
            first = True
            for oid, otype, ovmap_json in cursor:
                if not first: f.write(',\n')
                obj_dict = {
                    "ocel:oid": oid, "ocel:type": otype,
                    "ocel:ovmap": json.loads(ovmap_json)
                }
                f.write(f"    {json.dumps(obj_dict)}")
                first = False
            f.write('\n  ],\n')

            # 5. Object Relationships
            f.write('  "ocel:object-relationships": [\n')
            cursor = self.conn.execute("SELECT source_id, target_id, qualifier FROM object_relationships")
            first = True
            for sid, tid, qual in cursor:
                if not first: f.write(',\n')
                rel_dict = {
                    "ocel:sourceId": sid,
                    "ocel:targetId": tid,
                    "ocel:qualifier": qual
                }
                f.write(f"    {json.dumps(rel_dict)}")
                first = False
            f.write('\n  ]\n}') # Close JSON

        logger.info(f"Complete streaming export: log, events, objects, and relationships.")

    # Close
    def close(self):
        if self.conn:
            self.conn.close()
            logger.debug("Database connection closed")
