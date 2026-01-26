"""
OCEL MCP Server - Model Context Protocol server for domain-agnostic OCEL 2.0 analysis.

Modules:
- constants: Shared constants and configuration
- typing_ocel: Data types and dataclasses
- logger: Centralized logging
- ocel_config: Dynamic OCEL configuration loading
- data_loading: Smart OCEL loader
- ocel_query_engine: Query engine (five MVP queries)
- process_mining: PM4PY wrapper
- visualization_engine: Visualization generator
- response_builder: Unified response builder
- mcp_ocel_server: MCP core server
"""

from .mcp_ocel_server import OCELMCPServer, run_mcp_server

__version__ = "1.0.0"
__author__ = "ISA Group"

__all__ = [
    "OCELMCPServer",
    "run_mcp_server",
]
