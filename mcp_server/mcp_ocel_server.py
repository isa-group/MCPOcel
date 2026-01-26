"""
OCEL MCP Server core.
Implements JSON-RPC 2.0 protocol with five MVP tools.
"""

import json
import sys
from typing import Any, Dict, List, Optional

from . import logger, constants
from .ocel_config import OCELConfig, get_cached_config
from .data_loading import load_ocel, SmartOCELLoader
from .ocel_query_engine import OCELQueryEngine
from .process_mining import ProcessMiningEngine
from .visualization_engine import VisualizationEngine
from .response_builder import ResponseBuilder
from .typing_ocel import UnifiedMCPResponse


class OCELMCPServer:
    """Domain-agnostic MCP server for OCEL analysis."""
    
    def __init__(self, ocel_path: Optional[str] = None, debug: bool = False):
        """
        Initializes the MCP server.

        Args:
            ocel_path: Path to the OCEL file (takes precedence over env var).
            debug: Whether to enable DEBUG logging.
        """
        if debug:
            logger.set_log_level("DEBUG")
        else:
            logger.set_log_level("INFO")
        
        logger.info("Initializing OCEL MCP Server")
        
        try:
            self.config = get_cached_config(ocel_path)
            logger.info(f"OCEL configuration loaded: {len(self.config.event_types)} event types")
            
            if ocel_path:
                self.ocel_path = ocel_path
            else:
                import os
                self.ocel_path = os.getenv("OCEL_FILE", constants.DEFAULT_OCEL_PATH)
            
            self.ocel_data = load_ocel(self.ocel_path)
            logger.info(f"OCEL loaded: {self.ocel_path}")
            
            self.query_engine = OCELQueryEngine(self.ocel_data)
            self.mining_engine = ProcessMiningEngine(self.ocel_data)
            self.viz_engine = VisualizationEngine(self.ocel_data, self.mining_engine)
            
            logger.info("Engines initialized successfully")
            
        except Exception as e:
            logger.error(f"Error initializing server: {e}")
            raise
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """
        Returns the list of available MCP tools.

        Returns:
            List of tool definitions.
        """
        return [
            {
                "name": "trace_object_lifecycle",
                "description": "Trace the complete lifecycle of an object. "
                    "Returns all events it participates in ordered by timestamp, "
                    "showing related activities, involved objects, and verifiable references.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "object_id": {
                            "type": "string",
                            "description": f"OCEL object ID (ocel:oid). "
                                f"Available types: {', '.join(self.config.object_types)}",
                        }
                    },
                    "required": ["object_id"],
                },
            },
            {
                "name": "query_events_by_timerange",
                "description": "Query events within a specific time range. "
                    "Returns all events between two timestamps with participating object information.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "start_datetime": {
                            "type": "string",
                            "description": "Start datetime in ISO 8601 format (e.g., '2025-01-20T10:00:00' or '2025-01-20T10:00:00Z')",
                        },
                        "end_datetime": {
                            "type": "string",
                            "description": "End datetime in ISO 8601 format",
                        },
                    },
                    "required": ["start_datetime", "end_datetime"],
                },
            },
            {
                "name": "get_statistics_by_object_type",
                "description": "Calculate global OCEL statistics grouped by object type. "
                    "Returns object counts by type, distributions, and an analytical summary.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "detect_anomalies",
                "description": "Detect anomalies in the OCEL log. "
                    "Identifies objects without events (orphaned), events without objects, and broken references. "
                    "Classifies by type and severity.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "find_orphaned_objects",
                "description": "Find objects that do not participate in any event. "
                    "Useful to detect incomplete data or inconsistencies.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        ]
    
    def handle_tool_call(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Executes an MCP tool.

        Args:
            tool_name: Tool name.
            arguments: Input arguments.

        Returns:
            Unified response as a dict.

        Raises:
            ValueError: If the tool is unknown.
        """
        logger.info(f"Executing tool: {tool_name}")
        
        try:
            if tool_name == "trace_object_lifecycle":
                return self._handle_trace_lifecycle(arguments)
            elif tool_name == "query_events_by_timerange":
                return self._handle_timerange_query(arguments)
            elif tool_name == "get_statistics_by_object_type":
                return self._handle_statistics(arguments)
            elif tool_name == "detect_anomalies":
                return self._handle_anomalies(arguments)
            elif tool_name == "find_orphaned_objects":
                return self._handle_orphaned(arguments)
            else:
                raise ValueError(f"Unknown tool: {tool_name}")
        
        except Exception as e:
            logger.error(f"Error executing {tool_name}: {e}")
            return {
                "error": str(e),
                "tool": tool_name,
                "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
            }
    
    def _handle_trace_lifecycle(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handles `trace_object_lifecycle`."""
        object_id = args.get("object_id")
        if not object_id:
            raise ValueError("object_id is required")
        
        try:
            references = self.query_engine.trace_object_lifecycle(object_id)
            
            viz = None
            try:
                dfg = self.mining_engine.discover_dfg()
                viz = self.viz_engine.visualize_dfg(dfg)
            except Exception as e:
                logger.debug(f"Visualization not available: {e}")
            
            response = ResponseBuilder.build_lifecycle_response(
                object_id, references, viz
            )
            
            logger.info(f"Lifecycle trace completed: {len(references)} events")
            return response.to_dict()
        
        except ValueError as e:
            logger.warning(f"Object not found: {object_id}")
            raise
    
    def _handle_timerange_query(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handles `query_events_by_timerange`."""
        start = args.get("start_datetime")
        end = args.get("end_datetime")
        
        if not start or not end:
            raise ValueError("start_datetime and end_datetime are required")
        
        references = self.query_engine.query_events_by_timerange(start, end)
        
        response = ResponseBuilder.build_timerange_response(start, end, references)
        
        logger.info(f"Timerange query completed: {len(references)} events")
        return response.to_dict()
    
    def _handle_statistics(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handles `get_statistics_by_object_type`."""
        stats = self.query_engine.get_statistics_by_object_type()
        
        viz = None
        try:
            viz = self.viz_engine.generate_summary_visualization()
        except Exception as e:
            logger.debug(f"Visualización de resumen no disponible: {e}")
        
        response = ResponseBuilder.build_statistics_response(stats, viz)
        
        logger.info("Statistics completed")
        return response.to_dict()
    
    def _handle_anomalies(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handles `detect_anomalies`."""
        anomalies = self.query_engine.detect_anomalies()
        
        response = ResponseBuilder.build_anomalies_response(anomalies)
        
        logger.info(f"Anomalies detected: {len(anomalies)}")
        return response.to_dict()
    
    def _handle_orphaned(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handles `find_orphaned_objects`."""
        orphaned = self.query_engine.find_orphaned_objects()
        
        if hasattr(self.ocel_data, "objects"):
            total = len(self.ocel_data.objects)
        else:
            total = len(self.ocel_data.get("ocel:objects", {}))
        
        response = ResponseBuilder.build_orphaned_response(orphaned, total)
        
        logger.info(f"Orphaned objects found: {len(orphaned)}/{total}")
        return response.to_dict()
    
    def initialize(self) -> Dict[str, Any]:
        """
        MCP initialization (initialize message).

        Returns:
            Initialization object for the MCP protocol.
        """
        logger.info("Initializing MCP protocol")
        
        return {
            "protocolVersion": constants.MCP_VERSION,
            "capabilities": {
                "tools": {},
            },
            "serverInfo": {
                "name": constants.MCP_IMPLEMENTATION_NAME,
                "version": constants.MCP_IMPLEMENTATION_VERSION,
            },
        }


def run_mcp_server(ocel_path: Optional[str] = None, debug: bool = False) -> None:
    """
    Runs the MCP server in STDIO mode.

    Reads JSON-RPC 2.0 requests from stdin and writes responses to stdout.

    Args:
        ocel_path: Path to the OCEL file.
        debug: Whether to enable DEBUG logging.
    """
    import json
    
    logger.info("Starting MCP Server in STDIO mode")
    
    try:
        server = OCELMCPServer(ocel_path, debug)
        logger.info("Server ready to receive messages")
        
        for line in sys.stdin:
            try:
                request = json.loads(line.strip())
                
                if request.get("jsonrpc") != "2.0":
                    logger.warning(f"Invalid JSON-RPC version: {request.get('jsonrpc')}")
                    continue
                
                request_id = request.get("id")
                method = request.get("method")
                params = request.get("params", {})
                
                    logger.debug(f"Received message: {method}")
                
                if method == "initialize":
                    response = server.initialize()
                
                elif method == "tools/list":
                    response = {"tools": server.get_tools()}
                
                elif method == "tools/call":
                    tool_name = params.get("name")
                    tool_args = params.get("arguments", {})
                    response = server.handle_tool_call(tool_name, tool_args)
                
                else:
                    logger.warning(f"Unknown method: {method}")
                    response = {
                        "error": f"Unsupported method: {method}",
                    }
                
                if request_id is not None:
                    output = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": response,
                    }
                else:
                    output = {
                        "jsonrpc": "2.0",
                        "result": response,
                    }
                
                print(json.dumps(output))
                sys.stdout.flush()
            
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON: {e}")
            except Exception as e:
                logger.error(f"Error processing message: {e}")
    
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="MCP Server para análisis agnóstico de OCEL 2.0"
    )
    parser.add_argument(
        "--ocel-path",
        type=str,
        help="Ruta al archivo OCEL (prioridad sobre OCEL_FILE env var)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Habilitar DEBUG logging",
    )
    
    args = parser.parse_args()
    
    run_mcp_server(ocel_path=args.ocel_path, debug=args.debug)
