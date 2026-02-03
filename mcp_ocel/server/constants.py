"""
Shared constants for the OCEL MCP Server.
"""

from enum import Enum
from typing import Final

# Batch size for progress logs and event iteration.
DEFAULT_CHUNK_SIZE: Final[int] = 1000

DEFAULT_OCEL_PATH: Final[str] = "./log.json"

# Snapshot date of the MCP version used for traceability.
MCP_VERSION: Final[str] = "2026-01-20"
MCP_IMPLEMENTATION_NAME: Final[str] = "ocel-mcp-server"
# Initial semantic version of the server for external compatibility.
MCP_IMPLEMENTATION_VERSION: Final[str] = "0.1.0"


class LoadStrategy(str, Enum):
    """OCEL file loading strategy."""
    PM4PY = "pm4py"


class ErrorType(str, Enum):
    """Generic error types."""
    FILE_NOT_FOUND = "file_not_found"
    INVALID_OCEL = "invalid_ocel"
    SCHEMA_VALIDATION_ERROR = "schema_validation_error"
    QUERY_ERROR = "query_error"
    PROCESSING_ERROR = "processing_error"
    CONFIG_ERROR = "config_error"
    GRAPHVIZ_NOT_FOUND = "graphviz_not_found"

