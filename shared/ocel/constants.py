"""OCEL 2.0 Constants.

Shared constants and keys for OCEL 2.0 specification.
"""

from typing import Final

# OCEL 2.0 Schema Keys - String constants for JSON keys
EVT_TYPES: Final[str] = "eventTypes"
OBJ_TYPES_KEY: Final[str] = "objectTypes"
EVENTS: Final[str] = "events"
OBJECTS: Final[str] = "objects"
ATTR_TYPES: Final[str] = "attributeNames"

# OCEL 2.0 Schema Keys - Structured dict (camelCase format)
OCEL2_KEYS: Final[dict] = {
    "log": {
        "eventTypes",
        "objectTypes",
        "events",
        "objects",
    },
    "event": {
        "id",
        "type",
        "time",
        "attributes",
        "relationships",
    },
    "object": {
        "id",
        "type",
        "attributes",
        "relationships",
    },
    "relationship": {
        "objectId",
        "qualifier",
    },
}


