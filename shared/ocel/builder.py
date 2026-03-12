import sqlite3
import re
from pathlib import Path
from typing import Any, Dict, Set
from shared.ocel.model.models import Event, ObjectInstance

class OCELBuilder:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = None
        self.cursor = None

        # Caches to optimise performance and avoid collisions
        self.registered_event_types: Set[str] = set()
        self.registered_object_types: Set[str] = set()
        self.known_tables_columns: Dict[str, Set[str]] = {}

        # In-memory mirror of the object table: object_id -> object_type
        # Eliminates repeated SELECT calls from object_exists() and
        # _infer_qualifier_from_type() — kept in sync by insert_object().
        self.object_registry: Dict[str, str] = {}

        # Statistics
        self.stats = {"events": 0, "objects": 0, "relationships": 0}

    def __enter__(self):
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self._configure_sqlite()
        self._init_base_schema()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.conn.commit()
            self._print_stats()
            self.conn.close()

    def _configure_sqlite(self):
        # Optimisation for mass writing
        self.cursor.execute("PRAGMA journal_mode = WAL;")
        self.cursor.execute("PRAGMA synchronous = NORMAL;")
        self.cursor.execute("PRAGMA foreign_keys = OFF;") 

    def _init_base_schema(self):
        """Initialises the six mandatory base tables of the OCEL 2.0 standard."""
        base_stmts = [
            # 1. Base identifiers
            "CREATE TABLE IF NOT EXISTS event (ocel_id TEXT PRIMARY KEY, ocel_type TEXT)",
            "CREATE TABLE IF NOT EXISTS object (ocel_id TEXT PRIMARY KEY, ocel_type TEXT)",

            # 2. Relationships (composite PK: full integrity)
            """CREATE TABLE IF NOT EXISTS event_object (
                ocel_event_id TEXT,
                ocel_object_id TEXT,
                ocel_qualifier TEXT,
                PRIMARY KEY (ocel_event_id, ocel_object_id, ocel_qualifier)
            )""",
            """CREATE TABLE IF NOT EXISTS object_object (
                ocel_source_id TEXT,
                ocel_target_id TEXT,
                ocel_qualifier TEXT,
                PRIMARY KEY (ocel_source_id, ocel_target_id, ocel_qualifier)
            )""",

            # 3. Type mapping (Original Name -> Table Name)
            "CREATE TABLE IF NOT EXISTS event_map_type (ocel_type TEXT PRIMARY KEY, ocel_type_map TEXT)",
            "CREATE TABLE IF NOT EXISTS object_map_type (ocel_type TEXT PRIMARY KEY, ocel_type_map TEXT)"
        ]
        for stmt in base_stmts:
            self.cursor.execute(stmt)

        # Índex performance
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_eo_event ON event_object(ocel_event_id)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_eo_object ON event_object(ocel_object_id)")

    def _sanitize_name(self, name: str) -> str:
        """Converts arbitrary names to safe table namesHaz clic para usar esta alternativa."""
        return re.sub(r'[^a-zA-Z0-9]', '', name)

    def _get_sql_type(self, value: Any) -> str:
        if isinstance(value, int): return "INTEGER"
        if isinstance(value, float): return "REAL"
        # OCEL 2.0 uses TEXT for strings and dates, and INTEGER (0/1) or TEXT for booleans.
        if isinstance(value, bool): return "INTEGER"
        return "TEXT"

    def _ensure_type_table(self, type_name: str, attributes: Dict[str, Any], is_event: bool) -> str:
        """
        OCEL 2.0:
        1. Maps the type to a physical table.
        2. Creates the table if it does not exist.
        3. Adds columns if new attributes arrive (Schema Evolution).
        """
        prefix = "event" if is_event else "object"
        map_table = f"{prefix}_map_type"
        registry = self.registered_event_types if is_event else self.registered_object_types

        sanitized = self._sanitize_name(type_name)

        # 1. Register Mapping
        if type_name not in registry:
            self.cursor.execute(f"INSERT OR IGNORE INTO {map_table} VALUES (?, ?)", (type_name, sanitized))
            registry.add(type_name)

        table_name = f"{prefix}_{sanitized}"

        # 2. Create Table (if not cached)
        if table_name not in self.known_tables_columns:
            if is_event:
                # Events: Unique (Id)
                sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" ("ocel_id" TEXT PRIMARY KEY, "ocel_time" TEXT)'
                cols = {"ocel_id", "ocel_time"}
            else:
                # Objects: History (ID + Time + ChangedField make the row unique)
                sql = f"""CREATE TABLE IF NOT EXISTS "{table_name}" (
                    "ocel_id" TEXT,
                    "ocel_time" TEXT,
                    "ocel_changed_field" TEXT,
                    PRIMARY KEY ("ocel_id", "ocel_time", "ocel_changed_field")
                )"""
                cols = {"ocel_id", "ocel_time", "ocel_changed_field"}

            self.cursor.execute(sql)
            self.known_tables_columns[table_name] = cols

        # 3. Schema Evolution (ALTER TABLE)
        current_cols = self.known_tables_columns[table_name]
        for key, val in attributes.items():
            if key not in current_cols:
                sql_type = self._get_sql_type(val)
                try:
                    self.cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{key}" {sql_type}')
                    current_cols.add(key)
                except sqlite3.OperationalError:
                    pass # column already existed

        return table_name

    def insert_event(self, event: Event):
        # Strict validation: Event without object is not valid in OCEL 2.0
        if not event.relationships:
             raise ValueError(f"OCEL 2.0 Violation: Event {event.id} ({event.type}) has no object relationships.")

        # 1. Base Table (Idempotent)
        self.cursor.execute("INSERT OR IGNORE INTO event VALUES (?, ?)", (event.id, event.type))

        # 2. Dynamic Attribute Table
        table_name = self._ensure_type_table(event.type, event.attributes, is_event=True)

        cols = ['"ocel_id"', '"ocel_time"']
        vals = [event.id, event.time]

        for k, v in event.attributes.items():
            cols.append(f'"{k}"')
            vals.append(v if not isinstance(v, bool) else (1 if v else 0))

        placeholders = ", ".join(["?"] * len(vals))
        self.cursor.execute(f'INSERT OR IGNORE INTO "{table_name}" ({", ".join(cols)}) VALUES ({placeholders})', vals)

        # 3. Relationships (batch insert)
        if event.relationships:
            # Event -> [(event_id, obj_id, qualifier), ...]
            data = [(event.id, obj_id, qual) for obj_id, qual in event.relationships]
            self.cursor.executemany("INSERT OR IGNORE INTO event_object VALUES (?, ?, ?)", data)
            self.stats["relationships"] += len(data)

        self.stats["events"] += 1

    def insert_object(self, obj: ObjectInstance):
        # 1. Base Table
        self.cursor.execute("INSERT OR IGNORE INTO object VALUES (?, ?)", (obj.id, obj.type))
        if self.cursor.rowcount > 0:
            self.stats["objects"] += 1
        # Keep in-memory registry in sync (idempotent — type never changes for same id)
        self.object_registry[obj.id] = obj.type

        # 2. Snapshots (Change History)
        for snap in obj.snapshots:
            table_name = self._ensure_type_table(obj.type, snap.attributes, is_event=False)

            cols = ['"ocel_id"', '"ocel_time"', '"ocel_changed_field"']
            # NULL handling for composite PKs
            safe_changed = snap.changed_field if snap.changed_field is not None else 'RESERVED_FULL_UPDATE'
            vals = [obj.id, snap.time, safe_changed]

            for k, v in snap.attributes.items():
                cols.append(f'"{k}"')
                vals.append(v if not isinstance(v, bool) else (1 if v else 0))

            placeholders = ", ".join(["?"] * len(vals))
            self.cursor.execute(f'INSERT OR IGNORE INTO "{table_name}" ({", ".join(cols)}) VALUES ({placeholders})', vals)

        # 3. Object-Object Relationships
        if obj.related_objects:
             data = [(obj.id, target_id, qual) for target_id, qual in obj.related_objects]
             self.cursor.executemany("INSERT OR IGNORE INTO object_object VALUES (?, ?, ?)", data)
             self.stats["relationships"] += len(data)

    def object_exists(self, object_id: str) -> bool:
        return object_id in self.object_registry

    def _print_stats(self):
        print(f"--- OCEL 2.0 Generation Completed ---")
        print(f"Events: {self.stats['events']}")
        print(f"Objects: {self.stats['objects']}")
        print(f"Relations: {self.stats['relationships']}")