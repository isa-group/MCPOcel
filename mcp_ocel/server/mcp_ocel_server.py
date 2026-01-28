"""
OCEL MCP Server - SDK v1 Implementation.
Uses FastMCP with streamable-http transport for process-separated client/server.
"""

import os
import json
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from . import constants
from .ocel_config import OCELConfig, get_cached_config
from shared.logger.logging_config import get_logger, setup_logging
from .data_loading import load_ocel
from .ocel_query_engine import OCELQueryEngine
from .process_mining import ProcessMiningEngine
from .visualization_engine import VisualizationEngine
from .response_builder import ResponseBuilder

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


# Global state for OCEL data (initialized in lifespan)
_ocel_state: Dict[str, Any] = {}


def _ocel_to_dict(ocel_data: Any, config: OCELConfig) -> Dict[str, Any]:
    """Convert pm4py OCEL object to dict format for indexing."""
    result = {
        "ocel:global-log": {
            "ocel:attribute-names": config.attribute_names,
            "ocel:object-types": config.object_types,
        },
        "ocel:events": [],
        "ocel:objects": {},
    }
    
    try:
        if hasattr(ocel_data, "events"):
            events_df = ocel_data.events
            for _, row in events_df.iterrows():
                event = {
                    "ocel:eid": str(row.get("ocel:eid", "")),
                    "ocel:activity": str(row.get("ocel:activity", "")),
                    "ocel:timestamp": str(row.get("ocel:timestamp", "")),
                }
                result["ocel:events"].append(event)
        
        if hasattr(ocel_data, "objects"):
            objects_df = ocel_data.objects
            for _, row in objects_df.iterrows():
                oid = str(row.get("ocel:oid", ""))
                result["ocel:objects"][oid] = {
                    "ocel:type": str(row.get("ocel:type", "")),
                }
    except Exception as e:
        logger.warning(f"Error converting OCEL to dict: {e}")
    
    return result


@asynccontextmanager
async def ocel_lifespan(server: FastMCP):
    """
    Initialize OCEL resources when the server starts.
    This runs once when the server boots up.
    """
    from shared.logger.logging_config import LoggingConfig
    
    ocel_path = os.getenv("OCEL_FILE", constants.DEFAULT_OCEL_PATH)
    debug = os.getenv("OCEL_DEBUG", "false").lower() == "true"
    
    level = "DEBUG" if debug else "INFO"
    config = LoggingConfig(level=level)
    setup_logging(config)
    
    logger.info(f"Initializing OCEL MCP Server with {ocel_path}")
    
    try:
        # Load OCEL and configuration
        ocel_config = get_cached_config(ocel_path)
        ocel_data = load_ocel(ocel_path)
        
        # Initialize engines
        query_engine = OCELQueryEngine(ocel_data)
        mining_engine = ProcessMiningEngine(ocel_data)
        viz_engine = VisualizationEngine(ocel_data, mining_engine)
        
        # Initialize retrieval engine (optional)
        retrieval_engine = None
        RetrievalClass = _get_retrieval_engine()
        if RetrievalClass and RetrievalClass is not False:
            try:
                retrieval_engine = RetrievalClass()
                ocel_dict = _ocel_to_dict(ocel_data, ocel_config)
                retrieval_engine.index_ocel(ocel_dict)
                logger.info("OCEL indexed for hybrid search")
            except Exception as e:
                logger.warning(f"Failed to initialize retrieval engine: {e}")
        
        # Store in global state
        _ocel_state["config"] = ocel_config
        _ocel_state["ocel_data"] = ocel_data
        _ocel_state["ocel_path"] = ocel_path
        _ocel_state["query_engine"] = query_engine
        _ocel_state["mining_engine"] = mining_engine
        _ocel_state["viz_engine"] = viz_engine
        _ocel_state["retrieval_engine"] = retrieval_engine
        
        logger.info(
            f"Server ready: {len(ocel_config.event_types)} event types, "
            f"{len(ocel_config.object_types)} object types"
        )
        
        yield
        
    except Exception as e:
        logger.error(f"Error initializing server: {e}")
        raise
    finally:
        logger.info("Server shutting down")


# Create the MCP server with lifespan
mcp = FastMCP(
    name=constants.MCP_IMPLEMENTATION_NAME,
    lifespan=ocel_lifespan,
)


# ============================================================================
# TOOLS - The 5 MVP tools using decorators
# ============================================================================

@mcp.tool()
def trace_object_lifecycle(object_id: str) -> Dict[str, Any]:
    """
    Trace the complete lifecycle of an object.
    Returns all events it participates in ordered by timestamp,
    showing related activities, involved objects, and verifiable references.
    
    Args:
        object_id: OCEL object ID (ocel:oid)
    """
    query_engine = _ocel_state.get("query_engine")
    mining_engine = _ocel_state.get("mining_engine")
    viz_engine = _ocel_state.get("viz_engine")
    
    if not query_engine:
        return {"error": "Server not initialized"}
    
    try:
        references = query_engine.trace_object_lifecycle(object_id)
        
        viz = None
        try:
            dfg = mining_engine.discover_dfg()
            viz = viz_engine.visualize_dfg(dfg)
        except Exception:
            pass
        
        response = ResponseBuilder.build_lifecycle_response(object_id, references, viz)
        return response.to_dict()
    
    except ValueError as e:
        return {"error": str(e), "object_id": object_id}


@mcp.tool()
def query_events_by_timerange(start_datetime: str, end_datetime: str) -> Dict[str, Any]:
    """
    Query events within a specific time range.
    Returns all events between two timestamps with participating object information.
    
    Args:
        start_datetime: Start datetime in ISO 8601 format (e.g., '2025-01-20T10:00:00')
        end_datetime: End datetime in ISO 8601 format
    """
    query_engine = _ocel_state.get("query_engine")
    
    if not query_engine:
        return {"error": "Server not initialized"}
    
    references = query_engine.query_events_by_timerange(start_datetime, end_datetime)
    response = ResponseBuilder.build_timerange_response(start_datetime, end_datetime, references)
    return response.to_dict()


@mcp.tool()
def get_statistics_by_object_type() -> Dict[str, Any]:
    """
    Calculate global OCEL statistics grouped by object type.
    Returns object counts by type, distributions, and an analytical summary.
    """
    query_engine = _ocel_state.get("query_engine")
    viz_engine = _ocel_state.get("viz_engine")
    
    if not query_engine:
        return {"error": "Server not initialized"}
    
    stats = query_engine.get_statistics_by_object_type()
    
    viz = None
    try:
        viz = viz_engine.generate_summary_visualization()
    except Exception:
        pass
    
    response = ResponseBuilder.build_statistics_response(stats, viz)
    return response.to_dict()


@mcp.tool()
def detect_anomalies() -> Dict[str, Any]:
    """
    Detect anomalies in the OCEL log.
    Identifies objects without events (orphaned), events without objects, and broken references.
    """
    query_engine = _ocel_state.get("query_engine")
    
    if not query_engine:
        return {"error": "Server not initialized"}
    
    anomalies = query_engine.detect_anomalies()
    response = ResponseBuilder.build_anomalies_response(anomalies)
    return response.to_dict()


@mcp.tool()
def find_orphaned_objects() -> Dict[str, Any]:
    """
    Find objects that do not participate in any event.
    Useful to detect incomplete data or inconsistencies.
    """
    query_engine = _ocel_state.get("query_engine")
    ocel_data = _ocel_state.get("ocel_data")
    
    if not query_engine:
        return {"error": "Server not initialized"}
    
    orphaned = query_engine.find_orphaned_objects()
    
    if hasattr(ocel_data, "objects"):
        total = len(ocel_data.objects)
    else:
        total = len(ocel_data.get("ocel:objects", {}))
    
    response = ResponseBuilder.build_orphaned_response(orphaned, total)
    return response.to_dict()


@mcp.tool()
def search_ocel(
    query: str,
    top_k: int = 5,
    chunk_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Perform hybrid semantic search over OCEL data.
    Combines BM25 keyword matching with embedding-based semantic search.
    
    Args:
        query: Natural language query to search for
        top_k: Number of results to return (default: 5)
        chunk_types: Optional filter for chunk types ('schema' or 'data')
    """
    retrieval_engine = _ocel_state.get("retrieval_engine")
    
    if retrieval_engine is None:
        return {
            "error": "Hybrid search not available. Install sentence-transformers, chromadb, and rank-bm25.",
            "fallback": "Use get_schema_section resource instead.",
        }
    
    try:
        if chunk_types and "schema" in chunk_types:
            results = retrieval_engine.search_schema(query, top_k=top_k)
        elif chunk_types and "data" in chunk_types:
            results = retrieval_engine.search_data(query, top_k=top_k)
        else:
            results = retrieval_engine.search(query, top_k=top_k)
        
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
        return {"error": str(e), "query": query}


# ============================================================================
# RESOURCES - For exposing OCEL metadata
# ============================================================================

@mcp.resource("ocel://info")
def get_ocel_info() -> str:
    """Get metadata about the loaded OCEL file."""
    config = _ocel_state.get("config")
    ocel_data = _ocel_state.get("ocel_data")
    ocel_path = _ocel_state.get("ocel_path", "unknown")
    
    if not config or not ocel_data:
        return json.dumps({"error": "Server not initialized"})
    
    # Calculate statistics
    if hasattr(ocel_data, "events"):
        total_events = len(ocel_data.events)
        total_objects = len(ocel_data.objects)
        try:
            timestamps = sorted(ocel_data.events["ocel:timestamp"].tolist())
            start_date = str(timestamps[0])[:19] if timestamps else "N/A"
            end_date = str(timestamps[-1])[:19] if timestamps else "N/A"
        except Exception:
            start_date = end_date = "N/A"
    else:
        events = ocel_data.get("ocel:events", [])
        total_events = len(events)
        total_objects = len(ocel_data.get("ocel:objects", {}))
        start_date = end_date = "N/A"
    
    info = {
        "ocel_path": ocel_path,
        "object_types": config.object_types,
        "event_types": config.event_types,
        "total_objects": total_objects,
        "total_events": total_events,
        "start_date": start_date,
        "end_date": end_date,
    }
    
    return json.dumps(info, indent=2)


@mcp.resource("ocel://schema/{section}")
def get_schema_section(section: str) -> str:
    """
    Get OCEL 2.0 schema sections.
    
    Args:
        section: One of: eventTypes, objectTypes, events, objects, attributes
    """
    config = _ocel_state.get("config")
    
    if not config:
        return json.dumps({"error": "Server not initialized"})
    
    sections = {
        "eventTypes": {
            "section": "eventTypes",
            "data": config.event_types,
            "description": "List of all event types in the OCEL log",
        },
        "objectTypes": {
            "section": "objectTypes",
            "data": config.object_types,
            "description": "List of all object types in the OCEL log",
        },
        "attributes": {
            "section": "attributes",
            "data": config.attribute_names,
            "description": "Attribute names grouped by category",
        },
        "events": {
            "section": "events",
            "schema": {
                "ocel:eid": "string - Unique event identifier",
                "ocel:activity": "string - Activity/event type name",
                "ocel:timestamp": "datetime - ISO 8601 timestamp",
            },
            "description": "OCEL 2.0 event structure",
        },
        "objects": {
            "section": "objects",
            "schema": {
                "ocel:oid": "string - Unique object identifier",
                "ocel:type": "string - Object type name",
            },
            "description": "OCEL 2.0 object structure",
        },
    }
    
    result = sections.get(section, {"error": f"Unknown section: {section}"})
    return json.dumps(result, indent=2)


# ============================================================================
# Server runner functions
# ============================================================================

def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    ocel_path: Optional[str] = None,
    debug: bool = False,
    transport: str = "streamable-http",
) -> None:
    """
    Run the MCP server.
    
    Args:
        host: Host to bind (default: 127.0.0.1)
        port: HTTP port (default: 8000)
        ocel_path: Path to OCEL file
        debug: Enable debug logging
        transport: Transport mode: 'streamable-http', 'sse', or 'stdio'
    """
    if ocel_path:
        os.environ["OCEL_FILE"] = ocel_path
    if debug:
        os.environ["OCEL_DEBUG"] = "true"
    
    if transport == "stdio":
        print(f"Starting MCP Server in STDIO mode")
        print(f"OCEL file: {os.getenv('OCEL_FILE', constants.DEFAULT_OCEL_PATH)}")
        mcp.run(transport="stdio")
    else:
        print(f"Starting MCP Server on http://{host}:{port}/mcp")
        print(f"OCEL file: {os.getenv('OCEL_FILE', constants.DEFAULT_OCEL_PATH)}")
        mcp.run(
            transport=transport,
            host=host,
            port=port,
        )


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="OCEL MCP Server")
    parser.add_argument("--ocel-path", type=str, help="Path to OCEL file")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--transport",
        choices=["streamable-http", "sse", "stdio"],
        default="streamable-http",
        help="Transport mode (default: streamable-http)",
    )
    
    args = parser.parse_args()
    run_server(
        host=args.host,
        port=args.port,
        ocel_path=args.ocel_path,
        debug=args.debug,
        transport=args.transport,
    )
