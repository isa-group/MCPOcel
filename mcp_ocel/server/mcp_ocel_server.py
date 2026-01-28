"""
OCEL MCP Server core.
Implements JSON-RPC 2.0 protocol with five MVP tools.
"""

import json
import sys
from typing import Any, Dict, List, Optional

from . import constants
from .ocel_config import OCELConfig, get_cached_config
from shared.logger.logging_config import get_logger, setup_logging
from .data_loading import load_ocel, SmartOCELLoader
from .ocel_query_engine import OCELQueryEngine
from .process_mining import ProcessMiningEngine
from .visualization_engine import VisualizationEngine
from .response_builder import ResponseBuilder
from .typing_ocel import UnifiedMCPResponse

# Lazy import for retrieval engine (optional dependency)
_retrieval_engine = None

logger = get_logger(__name__)


def _get_retrieval_engine():
    """Lazy-load the retrieval engine to avoid import overhead."""
    global _retrieval_engine
    if _retrieval_engine is None:
        try:
            from mcp_ocel.server.retrieval import OCELRetrievalEngine
            _retrieval_engine = OCELRetrievalEngine
            logger.info("Hybrid retrieval engine loaded successfully")
        except ImportError as e:
            logger.warning(f"Retrieval engine not available: {e}")
            _retrieval_engine = False
    return _retrieval_engine

class OCELMCPServer:
    """Domain-agnostic MCP server for OCEL analysis."""
    
    def __init__(self, ocel_path: Optional[str] = None, debug: bool = False):
        """
        Initializes the MCP server.

        Args:
            ocel_path: Path to the OCEL file (takes precedence over env var).
            debug: Whether to enable DEBUG logging.
        """
        from shared.logger.logging_config import LoggingConfig
        
        level = "DEBUG" if debug else "INFO"
        config = LoggingConfig(level=level)
        setup_logging(config)
        
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
            
            # Initialize hybrid retrieval engine (optional)
            self.retrieval_engine = None
            self._init_retrieval_engine()
            
            logger.info("Engines initialized successfully")
            
        except Exception as e:
            logger.error(f"Error initializing server: {e}")
            raise
    
    def _init_retrieval_engine(self) -> None:
        """Initialize the hybrid retrieval engine for semantic search."""
        RetrievalEngine = _get_retrieval_engine()
        if RetrievalEngine and RetrievalEngine is not False:
            try:
                self.retrieval_engine = RetrievalEngine()
                # Index the OCEL data
                if hasattr(self.ocel_data, "events"):
                    # pm4py OCEL object - convert to dict
                    ocel_dict = self._ocel_to_dict()
                else:
                    ocel_dict = self.ocel_data
                self.retrieval_engine.index_ocel(ocel_dict)
                logger.info("OCEL indexed for hybrid search")
            except Exception as e:
                logger.warning(f"Failed to initialize retrieval engine: {e}")
                self.retrieval_engine = None
    
    def _ocel_to_dict(self) -> Dict[str, Any]:
        """Convert pm4py OCEL object to dict format for indexing."""
        result = {
            "ocel:global-log": {
                "ocel:attribute-names": self.config.attribute_names,
                "ocel:object-types": self.config.object_types,
            },
            "ocel:events": [],
            "ocel:objects": {},
        }
        
        try:
            # Convert events
            if hasattr(self.ocel_data, "events"):
                events_df = self.ocel_data.events
                for _, row in events_df.iterrows():
                    event = {
                        "ocel:eid": str(row.get("ocel:eid", "")),
                        "ocel:activity": str(row.get("ocel:activity", "")),
                        "ocel:timestamp": str(row.get("ocel:timestamp", "")),
                    }
                    result["ocel:events"].append(event)
            
            # Convert objects
            if hasattr(self.ocel_data, "objects"):
                objects_df = self.ocel_data.objects
                for _, row in objects_df.iterrows():
                    oid = str(row.get("ocel:oid", ""))
                    result["ocel:objects"][oid] = {
                        "ocel:type": str(row.get("ocel:type", "")),
                    }
        except Exception as e:
            logger.warning(f"Error converting OCEL to dict: {e}")
        
        return result
    
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

    def get_ocel_info(self) -> Dict[str, Any]:
        """
        Returns metadata about the loaded OCEL file.

        Returns:
            Dict with object_types, event_types, counts, and time range.
        """
        logger.info("Returning OCEL info")
        
        # Get counts
        if hasattr(self.ocel_data, "events"):
            total_events = len(self.ocel_data.events)
            total_objects = len(self.ocel_data.objects)
            # Extract timestamps from pm4py OCEL
            try:
                timestamps = sorted(self.ocel_data.events["ocel:timestamp"].tolist())
                start_date = str(timestamps[0])[:19] if timestamps else "N/A"
                end_date = str(timestamps[-1])[:19] if timestamps else "N/A"
            except Exception:
                start_date = "N/A"
                end_date = "N/A"
        else:
            events = self.ocel_data.get("ocel:events", [])
            objects = self.ocel_data.get("ocel:objects", {})
            total_events = len(events) if isinstance(events, list) else len(events)
            total_objects = len(objects)
            # Extract timestamps
            try:
                if isinstance(events, list):
                    timestamps = sorted([e.get("ocel:timestamp", "") for e in events if e.get("ocel:timestamp")])
                else:
                    timestamps = sorted([e.get("ocel:timestamp", "") for e in events.values() if e.get("ocel:timestamp")])
                start_date = str(timestamps[0])[:19] if timestamps else "N/A"
                end_date = str(timestamps[-1])[:19] if timestamps else "N/A"
            except Exception:
                start_date = "N/A"
                end_date = "N/A"
        
        return {
            "ocel_path": self.ocel_path,
            "object_types": self.config.object_types,
            "event_types": self.config.event_types,
            "total_objects": total_objects,
            "total_events": total_events,
            "start_date": start_date,
            "end_date": end_date,
        }

    def get_schema_section(self, section: Optional[str] = None) -> Dict[str, Any]:
        """
        Returns OCEL 2.0 schema sections on demand.

        Args:
            section: Specific section to retrieve. Options:
                - 'eventTypes': Event type definitions
                - 'objectTypes': Object type definitions
                - 'events': Event structure
                - 'objects': Object structure
                - 'attributes': Attribute definitions for all types
                - None: Returns available sections list

        Returns:
            Dict with requested schema section or list of available sections.
        """
        logger.info(f"Returning schema section: {section or 'index'}")

        available_sections = ["eventTypes", "objectTypes", "events", "objects", "attributes"]

        if section is None:
            # Return index of available sections with summary
            return {
                "available_sections": available_sections,
                "summary": {
                    "eventTypes": f"{len(self.config.event_types)} event types defined",
                    "objectTypes": f"{len(self.config.object_types)} object types defined",
                    "attributes": f"{len(self.config.attribute_names)} attribute categories",
                },
            }

        if section == "eventTypes":
            return {
                "section": "eventTypes",
                "data": self.config.event_types,
                "description": "List of all event types in the OCEL log",
            }

        if section == "objectTypes":
            return {
                "section": "objectTypes",
                "data": self.config.object_types,
                "description": "List of all object types in the OCEL log",
            }

        if section == "attributes":
            return {
                "section": "attributes",
                "data": self.config.attribute_names,
                "description": "Attribute names grouped by category (event, object, etc.)",
            }

        if section == "events":
            # Return schema structure for events (not the actual events)
            return {
                "section": "events",
                "schema": {
                    "ocel:eid": "string - Unique event identifier",
                    "ocel:activity": "string - Activity/event type name",
                    "ocel:timestamp": "datetime - ISO 8601 timestamp",
                    "ocel:omap": "array - List of related object IDs",
                    "ocel:vmap": "object - Event-specific attributes",
                },
                "description": "OCEL 2.0 event structure",
            }

        if section == "objects":
            # Return schema structure for objects (not the actual objects)
            return {
                "section": "objects",
                "schema": {
                    "ocel:oid": "string - Unique object identifier",
                    "ocel:type": "string - Object type name",
                    "ocel:ovmap": "object - Object-specific attributes",
                },
                "description": "OCEL 2.0 object structure",
            }

        return {
            "error": f"Unknown section: {section}",
            "available_sections": available_sections,
        }

    def search_ocel(
        self,
        query: str,
        top_k: int = 5,
        chunk_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Perform hybrid semantic search over OCEL data.

        Combines BM25 keyword matching with embedding-based semantic search
        using Reciprocal Rank Fusion (RRF) for optimal results.

        Args:
            query: Natural language query to search for.
            top_k: Number of results to return (default: 5).
            chunk_types: Optional filter for chunk types. Options:
                - 'schema': Schema-related (metadata, types, attributes)
                - 'data': Data chunks (events, objects)
                - None: Search all chunks

        Returns:
            Dict with search results containing relevant OCEL chunks.
        """
        logger.info(f"Searching OCEL for: {query[:50]}...")

        if self.retrieval_engine is None:
            return {
                "error": "Hybrid search not available. Install sentence-transformers, chromadb, and rank-bm25.",
                "fallback": "Use ocel/schema to get schema sections instead.",
            }

        try:
            # Choose search method based on chunk_types filter
            if chunk_types and "schema" in chunk_types:
                results = self.retrieval_engine.search_schema(query, top_k=top_k)
            elif chunk_types and "data" in chunk_types:
                results = self.retrieval_engine.search_data(query, top_k=top_k)
            else:
                results = self.retrieval_engine.search(query, top_k=top_k)

            formatted_results = []
            for result in results:
                formatted_results.append({
                    "content": result.get("content", ""),
                    "chunk_type": result.get("type", "unknown"),
                    "path": result.get("path", ""),
                    "score": round(result.get("score", 0.0), 4),
                    "metadata": result.get("metadata", {}),
                })

            return {
                "query": query,
                "total_results": len(formatted_results),
                "results": formatted_results,
            }

        except Exception as e:
            logger.error(f"Search error: {e}")
            return {
                "error": str(e),
                "query": query,
            }

    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle a single JSON-RPC 2.0 request.

        Args:
            request: Parsed JSON-RPC request.

        Returns:
            JSON-RPC response dict.
        """
        if request.get("jsonrpc") != "2.0":
            return {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid JSON-RPC version"}}

        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        logger.debug(f"Handling method: {method}")

        try:
            if method == "initialize":
                result = self.initialize()
            elif method == "ocel/info":
                result = self.get_ocel_info()
            elif method == "ocel/schema":
                section = params.get("section")
                result = self.get_schema_section(section)
            elif method == "ocel/search":
                query = params.get("query", "")
                top_k = params.get("top_k", 5)
                chunk_types = params.get("chunk_types")
                result = self.search_ocel(query, top_k, chunk_types)
            elif method == "tools/list":
                result = {"tools": self.get_tools()}
            elif method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                result = self.handle_tool_call(tool_name, tool_args)
            else:
                logger.warning(f"Unknown method: {method}")
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }

            response = {"jsonrpc": "2.0", "result": result}
            if request_id is not None:
                response["id"] = request_id
            return response

        except Exception as e:
            logger.error(f"Error handling {method}: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32000, "message": str(e)},
            }


def run_mcp_server_tcp(
    ocel_path: Optional[str] = None,
    debug: bool = False,
    host: str = "127.0.0.1",
    port: int = 9820,
) -> None:
    """
    Runs the MCP server in TCP mode.

    Listens for JSON-RPC 2.0 requests over TCP socket.

    Args:
        ocel_path: Path to the OCEL file.
        debug: Whether to enable DEBUG logging.
        host: Host to bind to.
        port: TCP port to listen on.
    """
    import socket
    import threading

    logger.info(f"Starting MCP Server in TCP mode on {host}:{port}")

    try:
        server = OCELMCPServer(ocel_path, debug)
    except Exception as e:
        logger.critical(f"Failed to initialize server: {e}")
        sys.exit(1)

    def handle_client(client_socket: socket.socket, address: tuple) -> None:
        """Handle a single client connection."""
        logger.info(f"Client connected: {address}")
        buffer = b""

        try:
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                buffer += chunk

                # Process complete lines (newline-delimited JSON)
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue

                    try:
                        request = json.loads(line.decode("utf-8"))
                        response = server.handle_request(request)
                        response_bytes = json.dumps(response).encode("utf-8") + b"\n"
                        client_socket.sendall(response_bytes)
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON from {address}: {e}")
                        error_response = {
                            "jsonrpc": "2.0",
                            "error": {"code": -32700, "message": "Parse error"},
                        }
                        client_socket.sendall(json.dumps(error_response).encode("utf-8") + b"\n")

        except Exception as e:
            logger.error(f"Error with client {address}: {e}")
        finally:
            client_socket.close()
            logger.info(f"Client disconnected: {address}")

    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((host, port))
        server_socket.listen(5)
        logger.info(f"Server listening on {host}:{port}")
        print(f"MCP Server ready on {host}:{port}")

        while True:
            client_socket, address = server_socket.accept()
            client_thread = threading.Thread(
                target=handle_client,
                args=(client_socket, address),
                daemon=True,
            )
            client_thread.start()

    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        server_socket.close()


def run_mcp_server_stdio(ocel_path: Optional[str] = None, debug: bool = False) -> None:
    """
    Runs the MCP server in STDIO mode.

    Reads JSON-RPC 2.0 requests from stdin and writes responses to stdout.

    Args:
        ocel_path: Path to the OCEL file.
        debug: Whether to enable DEBUG logging.
    """
    logger.info("Starting MCP Server in STDIO mode")

    try:
        server = OCELMCPServer(ocel_path, debug)
        logger.info("Server ready to receive messages")

        for line in sys.stdin:
            try:
                request = json.loads(line.strip())
                response = server.handle_request(request)
                print(json.dumps(response))
                sys.stdout.flush()

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON: {e}")
                error_response = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": "Parse error"},
                }
                print(json.dumps(error_response))
                sys.stdout.flush()
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
    parser.add_argument(
        "--mode",
        choices=["stdio", "tcp"],
        default="tcp",
        help="Transport mode: stdio or tcp (default: tcp)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="TCP host to bind (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9820,
        help="TCP port to listen on (default: 9820)",
    )

    args = parser.parse_args()

    if args.mode == "stdio":
        run_mcp_server_stdio(ocel_path=args.ocel_path, debug=args.debug)
    else:
        run_mcp_server_tcp(
            ocel_path=args.ocel_path,
            debug=args.debug,
            host=args.host,
            port=args.port,
        )
