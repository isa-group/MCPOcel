"""
OCEL MCP Tools and Resources Registration.

This module registers all MCP tools and resources with the FastMCP server.
Tools are dynamically introspected from the function decorators using helper functions.
"""

import inspect
import json
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from . import constants
from .response_builder import ResponseBuilder
from .typing_ocel import (
    ToolInfoDict,
    ToolParameterDict,
    InputSchemaDict,
    ListToolsResponseDict,
)
from shared.logger.logging_config import get_logger
from shared.logger.decorators import debug_log_tool
from shared.ocel.config import OCELConfig

logger = get_logger(__name__)


def _parse_docstring_parameters(func: Callable) -> Dict[str, str]:
    """
    Parse parameter descriptions from a function's docstring.

    Args:
        func: The function to extract parameters from.

    Returns:
        Dict mapping parameter names to their descriptions.
    """
    docstring = inspect.getdoc(func) or ""
    params = {}

    lines = docstring.split("\n")
    in_args = False

    for _, line in enumerate(lines):
        if "Args:" in line:
            in_args = True
            continue
        if in_args and ("Returns:" in line or "Raises:" in line or line.strip() == ""):
            break
        if in_args:
            parts = line.strip().split(":", 1)
            if len(parts) == 2:
                param_name = parts[0].strip()
                param_desc = parts[1].strip()
                params[param_name] = param_desc

    return params

def _build_dynamic_tools_list(mcp: FastMCP) -> List[ToolInfoDict]:
    """
    Build a dynamic list of available tools by introspecting the MCP server's tools.

    Args:
        mcp: The FastMCP server instance.

    Returns:
        List of ToolInfoDict representing all registered tools.
    """
    tools_list: List[ToolInfoDict] = []

    registered_tools = mcp._tool_manager.list_tools()
    
    for tool in registered_tools:
        # Extract parameters from auto-generated schema
        properties: Dict[str, ToolParameterDict] = {}
        required_params: List[str] = []
        
        # Parse docstring to get parameter descriptions
        param_docs = {}
        if hasattr(tool, "fn") and tool.fn:
            param_docs = _parse_docstring_parameters(tool.fn)
        
        if hasattr(tool, "parameters") and tool.parameters:
            schema = tool.parameters
            if isinstance(schema, dict):
                if "properties" in schema:
                    for param_name, param_info in schema["properties"].items():
                        param_type = param_info.get("type", "string")
                        # Get description from parsed docstring or param schema
                        description = param_docs.get(param_name, "")
                        if isinstance(description, dict):
                            description = description.get("description", "")
                        if not description and "description" in param_info:
                            description = param_info.get("description", "")
                        
                        properties[param_name] = ToolParameterDict(
                            type=param_type,
                            description=description,
                            title=param_name,
                        )
                
                if "required" in schema:
                    required_params = schema["required"]
        
        # Build inputSchema
        input_schema: InputSchemaDict = {
            "type": "object",
            "properties": properties,
            "required": required_params,
        }
        
        # Get description from tool
        description = tool.description or ""
        if description:
            description = description.strip().split("\n")[0]
        
        # Build tool info
        tool_info: ToolInfoDict = {
            "name": tool.name,
            "description": description,
            "inputSchema": input_schema,
        }
        
        tools_list.append(tool_info)

    return tools_list


# ---------------------------------------------------------------------------
# Cursor-chaining helpers
# ---------------------------------------------------------------------------

def _resolve_input_data(
    ocel_state: Dict[str, Any],
    input_cursor_id: Optional[str],
) -> Optional[List[Any]]:
    """
    Resolve an *input_cursor_id* to the full (unpaginated) list of items
    stored in that cursor.

    Returns ``None`` when *input_cursor_id* is ``None`` (meaning the tool
    should operate on the full OCEL).  Returns the item list otherwise.

    Raises:
        ValueError: If the cursor id cannot be resolved (expired / invalid).
    """
    if not input_cursor_id:
        return None

    cursor_store = ocel_state.get("cursor_store")
    if not cursor_store:
        raise ValueError("Cursor store not available")

    try:
        return cursor_store.get_all_items(input_cursor_id)
    except KeyError as exc:
        raise ValueError(str(exc)) from exc


def _filter_refs_by_timerange(
    data: List[Dict[str, Any]],
    start_dt: str,
    end_dt: str,
) -> List[Dict[str, Any]]:
    """
    Filter a list of event-reference dicts whose ``timestamp`` falls
    inside [start_dt, end_dt].
    """

    start = datetime.fromisoformat(start_dt.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_dt.replace("Z", "+00:00"))

    # Normalise to UTC-aware for safe comparison
    if start.tzinfo is None:
        start = start.replace(tzinfo=datetime.timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=datetime.timezone.utc)

    results: List[Dict[str, Any]] = []
    for ref in data:
        ts_raw = ref.get("timestamp", "")
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
        except (ValueError, TypeError):
            continue
        if start <= ts <= end:
            results.append(ref)
    return results


def _filter_refs_by_event_type(
    data: List[Dict[str, Any]],
    event_type: str,
) -> List[Dict[str, Any]]:
    """
    Filter a list of event-reference dicts by ``activity == event_type``.
    """
    return [ref for ref in data if ref.get("activity") == event_type]


def _filter_refs_by_object_type(
    data: List[Dict[str, Any]],
    object_type: str,
) -> List[Dict[str, Any]]:
    """
    Filter a list of event-reference dicts whose ``involved_objects``
    contain at least one object of the given *object_type*.
    """
    results: List[Dict[str, Any]] = []
    for ref in data:
        involved = ref.get("involved_objects", [])
        if any(obj.get("object_type") == object_type for obj in involved):
            results.append(ref)
    return results


def _filter_refs_by_object_id(
    data: List[Dict[str, Any]],
    object_id: str,
) -> List[Dict[str, Any]]:
    """
    Filter a list of event-reference dicts whose ``involved_objects``
    contain the given *object_id*.
    """
    results: List[Dict[str, Any]] = []
    for ref in data:
        involved = ref.get("involved_objects", [])
        if any(obj.get("object_id") == object_id for obj in involved):
            results.append(ref)
    return results


def register_tools(mcp: FastMCP, ocel_state: Dict[str, Any], ocel_lock: Any) -> None:
    """
    Register all MCP tools and resources.

    Args:
        mcp: FastMCP server instance.
        ocel_state: Global OCEL state dictionary.
        ocel_lock: Threading lock for synchronizing access to critical sections.
    """

    # =========================================================================
    # TOOLS
    # =========================================================================

    @mcp.tool()
    @debug_log_tool
    def trace_object_lifecycle(object_id: str, input_cursor_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Trace the full lifecycle of an object through all events.

        Args:
            object_id: The unique identifier of the object to trace.
            input_cursor_id: Optional cursor_id from a previous tool result to chain filters. When provided, filters within that subset instead of the full OCEL.

        Returns:
            Dict with cursor_id for the matching events.
        """
        try:
            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            input_data = _resolve_input_data(ocel_state, input_cursor_id)

            if input_data is not None:
                refs = _filter_refs_by_object_id(input_data, object_id)
            else:
                query_engine = ocel_state.get("query_engine")
                if not query_engine:
                    return {"error": "OCEL query engine not initialized"}

                references = query_engine.trace_object_lifecycle(object_id)
                refs = [ref.to_dict() for ref in references]

            cursor_id = cursor_store.create_cursor("trace_object_lifecycle", refs)
            return {"cursor_id": cursor_id}

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error in trace_object_lifecycle: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def query_events_by_timerange(start_datetime: str, end_datetime: str, input_cursor_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Query events within a specific time range.

        Args:
            start_datetime: Start time in ISO 8601 format (e.g., "2025-01-20T10:00:00Z").
            end_datetime: End time in ISO 8601 format (e.g., "2025-01-20T15:00:00Z").
            input_cursor_id: Optional cursor_id from a previous tool result to chain filters. When provided, filters within that subset instead of the full OCEL.

        Returns:
            Dict with cursor_id for the matching events.
        """
        try:
            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            input_data = _resolve_input_data(ocel_state, input_cursor_id)

            if input_data is not None:
                refs = _filter_refs_by_timerange(input_data, start_datetime, end_datetime)
            else:
                query_engine = ocel_state.get("query_engine")
                if not query_engine:
                    return {"error": "OCEL query engine not initialized"}

                references = query_engine.query_events_by_timerange(
                    start_datetime, end_datetime
                )
                refs = [ref.to_dict() for ref in references]

            cursor_id = cursor_store.create_cursor("query_events_by_timerange", refs)
            return {"cursor_id": cursor_id}

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error in query_events_by_timerange: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def get_statistics_by_object_type() -> Dict[str, Any]:
        """
        Get statistical information grouped by object type.

        Returns:
            Dict with statistics per object type.
        """
        try:
            query_engine = ocel_state.get("query_engine")
            if not query_engine:
                return {"error": "OCEL query engine not initialized"}

            stats = query_engine.get_statistics_by_object_type()
            response = ResponseBuilder.build_statistics_response(stats)

            return response.to_dict()

        except Exception as e:
            logger.error(f"Error in get_statistics_by_object_type: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def detect_anomalies() -> Dict[str, Any]:
        """
        Detect anomalies in the event log (orphaned objects, broken references).

        Returns:
            Dict with cursor_id for the detected anomalies.
        """
        try:
            query_engine = ocel_state.get("query_engine")
            if not query_engine:
                return {"error": "OCEL query engine not initialized"}

            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            anomalies = query_engine.detect_anomalies()
            refs = [anom.to_dict() for anom in anomalies]
            cursor_id = cursor_store.create_cursor("detect_anomalies", refs)
            return {"cursor_id": cursor_id}

        except Exception as e:
            logger.error(f"Error in detect_anomalies: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def find_orphaned_objects() -> Dict[str, Any]:
        """
        Find objects that have no associated events.

        Returns:
            Dict with cursor_id for the orphaned objects.
        """
        try:
            query_engine = ocel_state.get("query_engine")
            if not query_engine:
                return {"error": "OCEL query engine not initialized"}

            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            orphaned = query_engine.find_orphaned_objects()
            refs = [{"object_id": obj_id, "status": "orphaned"} for obj_id in orphaned]
            cursor_id = cursor_store.create_cursor("find_orphaned_objects", refs)
            return {"cursor_id": cursor_id}

        except Exception as e:
            logger.error(f"Error in find_orphaned_objects: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def list_available_tools() -> Dict[str, Any]:
        """
        List all available MCP tools with their descriptions and parameter schemas.

        Returns:
            Dict with list of tools and total count.
        """
        try:
            tools = _build_dynamic_tools_list(mcp)
            response: ListToolsResponseDict = {
                "tools": tools,
                "total_count": len(tools),
                "metadata": {
                    "generated_at": datetime.now().isoformat(),
                    "server": constants.MCP_IMPLEMENTATION_NAME,
                    "version": constants.MCP_IMPLEMENTATION_VERSION,
                },
            }
            return response

        except Exception as e:
            logger.error(f"Error in list_available_tools: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def search_ocel(
        query: str, top_k: int = 5, chunk_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Search the OCEL data using full-text search over all content including attribute values, object IDs, relationships, and schema definitions.

        Use this tool to find events or objects by any textual content: attribute values,
        activity names, object IDs, or type definitions.
        For discovering what attributes exist on each type, use chunk_types=["schema"].

        Args:
            query: Search query text.
            top_k: Number of results to return (default: 5).
            chunk_types: Optional list of chunk types to filter by. Valid values: ["event_types", "object_types", "events", "objects", "schema", "data"]. Use "schema" for event/object type definitions and their attributes, "data" for actual events/objects with their attribute values.

        Returns:
            Dict with search results and relevance scores.
        """
        try:
            with ocel_lock:
                retrieval_engine = ocel_state.get("retrieval_engine")
                if not retrieval_engine:
                    return {
                        "error": "Retrieval engine not available - search not supported"
                    }

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
            logger.error(f"Error in search_ocel: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def discover_dfg(
        object_type: Optional[str] = None, include_visualization: bool = False
    ) -> Dict[str, Any]:
        """
        Discover a Directly Follows Graph (DFG) for process discovery.

        Args:
            object_type: Optional object type filter.
            include_visualization: Whether to include SVG visualization.

        Returns:
            Dict with DFG edges, activities, and optional visualization.
        """
        try:
            mining_engine = ocel_state.get("mining_engine")
            if not mining_engine:
                return {"error": "Process mining engine not initialized"}

            dfg, freq = mining_engine.discover_dfg(object_type, use_cache=True)

            visualization = None
            if include_visualization:
                viz_engine = ocel_state.get("viz_engine")
                if viz_engine:
                    try:
                        visualization = viz_engine.visualize_dfg(dfg)
                    except Exception as e:
                        logger.warning(f"Could not generate DFG visualization: {e}")

            response = ResponseBuilder.build_dfg_response(
                dfg, visualization
            )
            return response.to_dict()

        except Exception as e:
            logger.error(f"Error in discover_dfg: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def discover_petri_net(
        object_type: Optional[str] = None, include_visualization: bool = False
    ) -> Dict[str, Any]:
        """
        Discover a Petri Net model for process analysis.

        Args:
            object_type: Optional object type filter.
            include_visualization: Whether to include SVG visualization.

        Returns:
            Dict with Petri net structure (places, transitions, markings).
        """
        try:
            mining_engine = ocel_state.get("mining_engine")
            if not mining_engine:
                return {"error": "Process mining engine not initialized"}

            pn_dict = mining_engine.discover_petri_net(object_type, use_cache=True)

            visualization = None
            if include_visualization:
                viz_engine = ocel_state.get("viz_engine")
                if viz_engine:
                    try:
                        visualization = viz_engine.visualize_petri_net(pn_dict)
                    except Exception as e:
                        logger.warning(f"Could not generate Petri net visualization: {e}")

            response = ResponseBuilder.build_petri_net_response(
                pn_dict, object_type, visualization
            )
            return response.to_dict()

        except Exception as e:
            logger.error(f"Error in discover_petri_net: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def get_process_variants(
        object_type: Optional[str] = None, limit: int = 10
    ) -> Dict[str, Any]:
        """
        Extract and list process variants (activity sequences).

        Args:
            object_type: Optional object type filter.
            limit: Maximum number of variants to return (default: 10).

        Returns:
            Dict with cursor_id for the variants.
        """
        try:
            mining_engine = ocel_state.get("mining_engine")
            if not mining_engine:
                return {"error": "Process mining engine not initialized"}

            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            variants = mining_engine.extract_process_variants(object_type, limit)
            refs = [
                {
                    "variant_id": i + 1,
                    "sequence": " → ".join(v.get("activity_sequence", [])),
                    "frequency": v.get("frequency", 0),
                    "sample_objects": v.get("sample_objects", v.get("sample_events", [])),
                }
                for i, v in enumerate(variants)
            ]
            cursor_id = cursor_store.create_cursor("get_process_variants", refs)
            return {"cursor_id": cursor_id}

        except Exception as e:
            logger.error(f"Error in get_process_variants: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def get_performance_metrics(object_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Calculate performance metrics (flow time, processing time, etc.).

        Args:
            object_type: Optional object type filter.

        Returns:
            Dict with performance metrics including mean, median, and percentiles (in seconds).
        """
        try:
            mining_engine = ocel_state.get("mining_engine")
            if not mining_engine:
                return {"error": "Process mining engine not initialized"}

            metrics = mining_engine.get_performance_metrics(object_type)
            response = ResponseBuilder.build_performance_response(metrics)
            return response.to_dict()

        except Exception as e:
            logger.error(f"Error in get_performance_metrics: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def detect_bottlenecks(
        object_type: Optional[str] = None, threshold_percentile: float = 75.0
    ) -> Dict[str, Any]:
        """
        Detect performance bottlenecks in the process.

        Args:
            object_type: Optional object type filter.
            threshold_percentile: Percentile threshold for bottleneck detection (0-100, default: 75).

        Returns:
            Dict with cursor_id for the detected bottlenecks.
        """
        try:
            mining_engine = ocel_state.get("mining_engine")
            if not mining_engine:
                return {"error": "Process mining engine not initialized"}

            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            bottlenecks = mining_engine.detect_bottlenecks(
                object_type, threshold_percentile
            )
            refs = bottlenecks if isinstance(bottlenecks, list) else [bottlenecks]
            cursor_id = cursor_store.create_cursor("detect_bottlenecks", refs)
            return {"cursor_id": cursor_id}

        except Exception as e:
            logger.error(f"Error in detect_bottlenecks: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def check_conformance(object_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Check process conformance against discovered model.

        Args:
            object_type: Optional object type filter.

        Returns:
            Dict with conformance metrics and non-conforming traces.
        """
        try:
            mining_engine = ocel_state.get("mining_engine")
            if not mining_engine:
                return {"error": "Process mining engine not initialized"}

            conformance = mining_engine.check_conformance(object_type)
            response = ResponseBuilder.build_conformance_response(
                conformance, object_type
            )
            return response.to_dict()

        except Exception as e:
            logger.error(f"Error in check_conformance: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def analyze_object_interactions() -> Dict[str, Any]:
        """
        Analyze interactions between different objects in the event log.

        Args:

        Returns:
            Dict with cursor_id for the object interaction patterns.
        """
        try:
            mining_engine = ocel_state.get("mining_engine")
            if not mining_engine:
                return {"error": "Process mining engine not initialized"}

            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            interactions = mining_engine.analyze_object_interactions()
            refs = interactions if isinstance(interactions, list) else [interactions]
            cursor_id = cursor_store.create_cursor("analyze_object_interactions", refs)
            return {"cursor_id": cursor_id}

        except Exception as e:
            logger.error(f"Error in analyze_object_interactions: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def get_available_resource_attributes() -> Dict[str, Any]:
        """
        Get list of available resource attributes for social network analysis.

        Returns:
            Dict with available resource attribute names.
        """
        try:
            mining_engine = ocel_state.get("mining_engine")
            if not mining_engine:
                return {"error": "Process mining engine not initialized"}

            attributes = mining_engine.get_available_resource_attributes()
            return {
                "attributes": attributes,
                "total_count": len(attributes),
            }

        except Exception as e:
            logger.error(f"Error in get_available_resource_attributes: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def discover_social_network(resource_attribute: str) -> Dict[str, Any]:
        """
        Discover social network of resources (e.g., people, systems).

        Args:
            resource_attribute: The resource attribute to analyze (e.g., "resource", "manager").

        Returns:
            Dict with social network graph data (nodes, edges, metrics).
        """
        try:
            mining_engine = ocel_state.get("mining_engine")
            if not mining_engine:
                return {"error": "Process mining engine not initialized"}

            social_network = mining_engine.discover_social_network(resource_attribute)
            response = ResponseBuilder.build_social_network_response(
                social_network
            )
            return response.to_dict()

        except Exception as e:
            logger.error(f"Error in discover_social_network: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def filter_by_event_type(
        event_type: str,
        input_cursor_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Filter events by exact event type (activity name).

        Use this tool for precise filtering by activity instead of the fuzzy text matching of search_ocel.

        Args:
            event_type: Exact event type / activity name to filter for.
            input_cursor_id: Optional cursor_id from a previous tool result to chain filters. When provided, filters within that subset instead of the full OCEL.

        Returns:
            Dict with cursor_id for the matching events.
        """
        try:
            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            input_data = _resolve_input_data(ocel_state, input_cursor_id)

            if input_data is not None:
                refs = _filter_refs_by_event_type(input_data, event_type)
            else:
                query_engine = ocel_state.get("query_engine")
                if not query_engine:
                    return {"error": "OCEL query engine not initialized"}
                references = query_engine.get_events_by_event_type(event_type)
                refs = [ref.to_dict() for ref in references]

            cursor_id = cursor_store.create_cursor("filter_by_event_type", refs)
            return {"cursor_id": cursor_id}

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error in filter_by_event_type: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def filter_by_object_type(
        object_type: str,
        input_cursor_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Filter events by object type — returns all events that involve at
        least one object of the given type.

        Use this tool for precise filtering by object type instead of the fuzzy text matching
        of search_ocel.

        Args:
            object_type: Exact object type name to filter for.
            input_cursor_id: Optional cursor_id from a previous tool result to chain filters. When provided, filters within that subset instead of the full OCEL.

        Returns:
            Dict with cursor_id for the matching events.
        """
        try:
            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            input_data = _resolve_input_data(ocel_state, input_cursor_id)

            if input_data is not None:
                refs = _filter_refs_by_object_type(input_data, object_type)
            else:
                query_engine = ocel_state.get("query_engine")
                if not query_engine:
                    return {"error": "OCEL query engine not initialized"}
                references = query_engine.get_events_by_object_type(object_type)
                refs = [ref.to_dict() for ref in references]

            cursor_id = cursor_store.create_cursor("filter_by_object_type", refs)
            return {"cursor_id": cursor_id}

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error in filter_by_object_type: {e}")
            return {"error": f"Internal error: {str(e)}"}

    # =========================================================================
    # CURSOR INSPECTION & SET OPERATIONS
    # =========================================================================

    @mcp.tool()
    @debug_log_tool
    def get_total_from_cursor_id(cursor_id: str) -> Dict[str, Any]:
        """
        Return the total number of items stored in a cursor without loading the data.

        Use this instead of fetching full results when you only need a count.

        Args:
            cursor_id: The cursor identifier returned by a previous tool call.

        Returns:
            Dict with cursor_id and total item count.
        """
        try:
            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            total = cursor_store.get_total(cursor_id)
            return {"cursor_id": cursor_id, "total": total}

        except KeyError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error in get_total_from_cursor_id: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def get_timerange_by_cursor_id(cursor_id: str) -> Dict[str, Any]:
        """
        Return the temporal range (start, end, duration) of the events in a cursor
        without loading the full data.

        Only available for cursors produced by event-filtering tools
        (e.g., filter_by_event_type, query_events_by_timerange, trace_object_lifecycle).
        Use this to learn the temporal bounds of a filtered subset before deciding
        how to partition it further.

        Args:
            cursor_id: The cursor identifier returned by a previous tool call.

        Returns:
            Dict with cursor_id, start (ISO 8601), end (ISO 8601), and duration_seconds.
        """
        try:
            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            timerange = cursor_store.get_timerange(cursor_id)
            return {"cursor_id": cursor_id, **timerange}

        except KeyError as e:
            return {"error": str(e)}
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error in get_timerange_by_cursor_id: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def intersect_cursors(cursor_id_1: str, cursor_id_2: str) -> Dict[str, Any]:
        """
        Compute the intersection of two event cursors by event_id.

        Returns a new cursor containing only events present in BOTH cursors.
        Useful for combining independent filter results without loading either
        dataset into the LLM context.

        Both cursors must contain event-reference items (produced by event-
        filtering tools). Non-event cursors (e.g. from find_orphaned_objects)
        are not supported.

        Args:
            cursor_id_1: First cursor identifier.
            cursor_id_2: Second cursor identifier.

        Returns:
            Dict with cursor_id for the intersection result.
        """
        try:
            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            items_1 = cursor_store.get_all_items(cursor_id_1)
            items_2 = cursor_store.get_all_items(cursor_id_2)

            ids_2 = {item["event_id"] for item in items_2 if "event_id" in item}
            result = [item for item in items_1 if item.get("event_id") in ids_2]

            cursor_id = cursor_store.create_cursor("intersect_cursors", result)
            return {"cursor_id": cursor_id}

        except KeyError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error in intersect_cursors: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def union_cursors(cursor_id_1: str, cursor_id_2: str) -> Dict[str, Any]:
        """
        Compute the union of two event cursors, deduplicated by event_id.

        Returns a new cursor containing all events present in EITHER cursor,
        with duplicates removed. Useful for merging results from parallel
        filter paths without loading either dataset into the LLM context.

        Both cursors must contain event-reference items (produced by event-
        filtering tools). Non-event cursors (e.g. from find_orphaned_objects)
        are not supported.

        Args:
            cursor_id_1: First cursor identifier.
            cursor_id_2: Second cursor identifier.

        Returns:
            Dict with cursor_id for the union result.
        """
        try:
            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            items_1 = cursor_store.get_all_items(cursor_id_1)
            items_2 = cursor_store.get_all_items(cursor_id_2)

            seen: set = set()
            result = []
            for item in items_1 + items_2:
                eid = item.get("event_id")
                if eid:
                    if eid not in seen:
                        seen.add(eid)
                        result.append(item)
                else:
                    result.append(item)

            cursor_id = cursor_store.create_cursor("union_cursors", result)
            return {"cursor_id": cursor_id}

        except KeyError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error in union_cursors: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def get_summary_from_cursor_id(cursor_id: str) -> Dict[str, Any]:
        """
        Return a lightweight summary of the cursor without loading the full data.

        Reports total item count, activity types, object types, and time range.
        Only activity/object/time fields are populated for event-reference cursors
        (produced by event-filtering tools).
        Use this to characterise a subset before deciding whether to fetch it.

        Args:
            cursor_id: The cursor identifier returned by a previous tool call.

        Returns:
            Dict with cursor_id, total, activity_types, object_types, time_start, time_end.
        """
        try:
            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            summary = cursor_store.get_summary(cursor_id)
            return {"cursor_id": cursor_id, **summary}

        except KeyError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error in get_summary_from_cursor_id: {e}")
            return {"error": f"Internal error: {str(e)}"}

    # =========================================================================
    # CURSOR FETCH
    # =========================================================================

    @mcp.tool()
    @debug_log_tool
    def get_cursor_results(cursor_id: str) -> Dict[str, Any]:
        """
        Retrieve ALL data stored in a cursor.

        Call this only for the final filtered subset you intend to present to the user.
        For counts, time ranges, or type composition, prefer the cheaper inspection
        tools.

        Args:
            cursor_id: The cursor identifier returned by a previous tool call.

        Returns:
            Dict with cursor_id, total item count, and the full results list.
        """
        try:
            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            items = cursor_store.get_all_items(cursor_id)
            return {"cursor_id": cursor_id, "total": len(items), "results": items}

        except KeyError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error in get_cursor_results: {e}")
            return {"error": f"Internal error: {str(e)}"}

    # =========================================================================
    # RESOURCES
    # =========================================================================

    @mcp.resource("server://info")
    def get_server_info() -> str:
        """
        Get server metadata and status information.

        Returns:
            JSON string with server info.
        """
        info = {
            "server": constants.MCP_IMPLEMENTATION_NAME,
            "version": constants.MCP_IMPLEMENTATION_VERSION,
            "ocel_loaded": ocel_state.get("ocel_data") is not None,
            "generated_at": datetime.now().isoformat()
        }
        return json.dumps(info, indent=2)

    @mcp.resource("ocel://info")
    def get_ocel_info() -> str:
        """
        Get OCEL file metadata (types, counts, time range).

        Returns:
            JSON string with OCEL metadata.
        """
        try:
            ocel_config: OCELConfig = ocel_state.get("config")
            ocel_data = ocel_state.get("ocel_data")
            ocel_path = ocel_state.get("ocel_path")

            if not ocel_config or ocel_data is None:
                return json.dumps({"error": "OCEL not initialized"})

            # Get time range using pm4py's event_timestamp attribute
            events_df = ocel_data.events
            timestamp_col = ocel_data.event_timestamp
            timestamps = events_df[timestamp_col].dropna()
            start_date = timestamps.min().isoformat() if len(timestamps) > 0 else "N/A"
            end_date = timestamps.max().isoformat() if len(timestamps) > 0 else "N/A"

            info = {
                "file_path": ocel_path,
                "event_types": list(ocel_config.event_types),
                "object_types": list(ocel_config.object_types),
                "total_events": len(ocel_data.events),
                "total_objects": len(ocel_data.objects),
                "total_relations": len(ocel_data.relations),
                "start_date": start_date,
                "end_date": end_date,
                "generated_at": datetime.now().isoformat()
            }
            return json.dumps(info, indent=2)

        except Exception as e:
            logger.error(f"Error in get_ocel_info: {e}")
            return json.dumps({"error": f"Internal error: {str(e)}"})

    @mcp.resource("ocel://schema/{section}")
    def get_schema_section(section: str) -> str:
        """
        Get a specific section of the OCEL schema.

        Args:
            section: Schema section name (eventTypes, objectTypes, attributes, etc.).

        Returns:
            JSON string with schema section.
        """
        try:
            ocel_config: OCELConfig = ocel_state.get("config")

            if not ocel_config:
                return json.dumps({"error": "OCEL not initialized"})

            section_lower = section.lower()

            if section_lower == "eventtypes":
                schema = {
                    "eventTypes": list(ocel_config.event_types),
                }
            elif section_lower == "objecttypes":
                schema = {
                    "objectTypes": list(ocel_config.object_types),
                }
            elif section_lower == "attributes":
                # attribute_names is a Dict[str, List[str]] mapping type names to attribute lists
                schema = {
                    "attributesByType": ocel_config.attribute_names,
                }
            elif section_lower == "all":
                schema = {
                    "eventTypes": list(ocel_config.event_types),
                    "objectTypes": list(ocel_config.object_types),
                    "attributesByType": ocel_config.attribute_names,
                }
            else:
                return json.dumps({
                    "error": f"Unknown schema section: {section}. "
                            "Try: eventTypes, objectTypes, attributes, all"
                })

            return json.dumps(schema, indent=2)

        except Exception as e:
            logger.error(f"Error in get_schema_section: {e}")
            return json.dumps({"error": f"Internal error: {str(e)}"})

    tools_count = len(mcp._tool_manager.list_tools())
    resources_count = len(mcp._resource_manager.list_resources()) + len(mcp._resource_manager.list_templates())
    logger.info(
        f"Registered {tools_count} tools and {resources_count} resources"
    )
