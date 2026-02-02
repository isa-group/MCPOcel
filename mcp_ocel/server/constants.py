"""
Shared constants for the OCEL MCP Server.
"""

from enum import Enum
from typing import Final

# Threshold (MB) to load into memory with PM4PY without exhausting RAM on typical laptops.
FILE_SIZE_SMALL: Final[int] = 100

# Between 100MB-1GB we prioritize ijson streaming to avoid memory spikes
FILE_SIZE_MEDIUM: Final[int] = 1000

DEFAULT_OCEL_PATH: Final[str] = "./log.json"

# Batch size used for both streaming (ijson) and progress logs; balances
# progress granularity without flooding the logger.
DEFAULT_CHUNK_SIZE: Final[int] = 1000

# Snapshot date of the MCP version used for traceability.
MCP_VERSION: Final[str] = "2026-01-20"
MCP_IMPLEMENTATION_NAME: Final[str] = "ocel-mcp-server"
# Initial semantic version of the server for external compatibility.
MCP_IMPLEMENTATION_VERSION: Final[str] = "0.1.0"


class LoadStrategy(str, Enum):
    """OCEL file loading strategy."""
    PM4PY = "pm4py"  # < 100MB
    IJSON = "ijson"  # >= 100MB (streaming)


class ErrorType(str, Enum):
    """Generic error types."""
    FILE_NOT_FOUND = "file_not_found"
    INVALID_OCEL = "invalid_ocel"
    SCHEMA_VALIDATION_ERROR = "schema_validation_error"
    QUERY_ERROR = "query_error"
    PROCESSING_ERROR = "processing_error"
    CONFIG_ERROR = "config_error"
    GRAPHVIZ_NOT_FOUND = "graphviz_not_found"


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
