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


def _infer_parameter_type(param_name: str, annotation: Any) -> str:
    """
    Infer JSON Schema type from a Python type annotation.

    Args:
        param_name: The parameter name (for context).
        annotation: The type annotation.

    Returns:
        JSON Schema type string ("string", "number", "integer", "boolean", "array", "object").
    """
    if annotation == inspect.Parameter.empty:
        return "string"

    annotation_str = str(annotation).lower()

    if "int" in annotation_str:
        return "integer"
    elif "float" in annotation_str:
        return "number"
    elif "bool" in annotation_str:
        return "boolean"
    elif "list" in annotation_str or "sequence" in annotation_str:
        return "array"
    elif "dict" in annotation_str:
        return "object"
    else:
        return "string"


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


def _paginate_response(
    response_dict: Dict[str, Any],
    tool_name: str,
    cursor_store: Any,
    page_size: int = constants.DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    """
    Store the ``references`` list in the cursor store and inject a
    ``cursor_id`` into the response metadata.

    * When references **exceed** *page_size* the list is truncated to the
      first page and full ``pagination`` metadata is added (existing
      behaviour).
    * When references **fit** in a single page, the list is left intact
      but a ``cursor_id`` is still stored so that downstream tools can
      use it via ``input_cursor_id`` for chaining.

    Returns the (possibly modified) response dict.
    """
    refs = response_dict.get("references")
    if refs is None or not isinstance(refs, list):
        return response_dict

    total = len(refs)
    if total == 0:
        return response_dict

    import math

    cursor_id = cursor_store.create_cursor(tool_name, refs, page_size)
    total_pages = max(1, math.ceil(total / page_size))

    if total > page_size:
        # Multi-page: truncate and add full pagination block
        response_dict["references"] = refs[:page_size]
        response_dict["pagination"] = {
            "cursor_id": cursor_id,
            "page": 1,
            "total_pages": total_pages,
            "total_items": total,
            "page_size": page_size,
            "has_more": True,
            "hint": (
                f"Showing {page_size} of {total} items. "
                f"Use get_cursor_results(cursor_id='{cursor_id}', page=2) "
                f"to retrieve more pages. "
                f"To chain results into another tool, pass "
                f"input_cursor_id='{cursor_id}'."
            ),
        }
    else:
        # Single page: keep all references, expose cursor_id for chaining
        response_dict["pagination"] = {
            "cursor_id": cursor_id,
            "page": 1,
            "total_pages": 1,
            "total_items": total,
            "page_size": page_size,
            "has_more": False,
            "hint": (
                f"All {total} items returned. "
                f"To chain these results into another tool, pass "
                f"input_cursor_id='{cursor_id}'."
            ),
        }
    return response_dict


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
    from datetime import datetime as _dt, timezone as _tz

    start = _dt.fromisoformat(start_dt.replace("Z", "+00:00"))
    end = _dt.fromisoformat(end_dt.replace("Z", "+00:00"))

    # Normalise to UTC-aware for safe comparison
    if start.tzinfo is None:
        start = start.replace(tzinfo=_tz.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=_tz.utc)

    results: List[Dict[str, Any]] = []
    for ref in data:
        ts_raw = ref.get("timestamp", "")
        if not ts_raw:
            continue
        try:
            ts = _dt.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=_tz.utc)
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
    def trace_object_lifecycle(object_id: str, total_only: bool = False, input_cursor_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Trace the full lifecycle of an object through all events.

        Args:
            object_id: The unique identifier of the object to trace.
            total_only: If True, return only the total count of events instead of full data.
            input_cursor_id: Optional cursor_id from a previous tool result to chain filters. When provided, the tool filters within that subset instead of the full OCEL.

        Returns:
            Dict with event references, summary, and metadata.
        """
        try:
            input_data = _resolve_input_data(ocel_state, input_cursor_id)

            if input_data is not None:
                filtered = _filter_refs_by_object_id(input_data, object_id)
                if total_only:
                    return {"total": len(filtered)}
                response = ResponseBuilder.build_lifecycle_response(
                    object_id, [], visualization=None
                )
                result = response.to_dict()
                result["references"] = filtered
                result["metadata"]["total_events"] = len(filtered)
                result["metadata"]["source"] = "cursor_chain"
            else:
                query_engine = ocel_state.get("query_engine")
                if not query_engine:
                    return {"error": "OCEL query engine not initialized"}

                references = query_engine.trace_object_lifecycle(object_id)

                if total_only:
                    return {"total": len(references)}

                response = ResponseBuilder.build_lifecycle_response(
                    object_id, references
                )
                result = response.to_dict()

            cursor_store = ocel_state.get("cursor_store")
            if cursor_store:
                result = _paginate_response(result, "trace_object_lifecycle", cursor_store)

            return result

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error in trace_object_lifecycle: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def query_events_by_timerange(start_datetime: str, end_datetime: str, total_only: bool = False, input_cursor_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Query events within a specific time range.

        Args:
            start_datetime: Start time in ISO 8601 format (e.g., "2025-01-20T10:00:00Z").
            end_datetime: End time in ISO 8601 format (e.g., "2025-01-20T15:00:00Z").
            total_only: If True, return only the total count of events instead of full data.
            input_cursor_id: Optional cursor_id from a previous tool result to chain filters. When provided, the tool filters within that subset instead of the full OCEL.

        Returns:
            Dict with event references, summary, and metadata.
        """
        try:
            input_data = _resolve_input_data(ocel_state, input_cursor_id)

            if input_data is not None:
                filtered = _filter_refs_by_timerange(input_data, start_datetime, end_datetime)
                if total_only:
                    return {"total": len(filtered)}
                response = ResponseBuilder.build_timerange_response(
                    start_datetime, end_datetime, []
                )
                result = response.to_dict()
                result["references"] = filtered
                result["metadata"]["total_events"] = len(filtered)
                result["metadata"]["source"] = "cursor_chain"
            else:
                query_engine = ocel_state.get("query_engine")
                if not query_engine:
                    return {"error": "OCEL query engine not initialized"}

                references = query_engine.query_events_by_timerange(
                    start_datetime, end_datetime
                )

                if total_only:
                    return {"total": len(references)}

                response = ResponseBuilder.build_timerange_response(
                    start_datetime, end_datetime, references
                )
                result = response.to_dict()

            cursor_store = ocel_state.get("cursor_store")
            if cursor_store:
                result = _paginate_response(result, "query_events_by_timerange", cursor_store)

            return result

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error in query_events_by_timerange: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def get_statistics_by_object_type(total_only: bool = False) -> Dict[str, Any]:
        """
        Get statistical information grouped by object type.

        Args:
            total_only: If True, return only the total count of object types instead of full data.

        Returns:
            Dict with statistics by object type and metadata.
        """
        try:
            query_engine = ocel_state.get("query_engine")
            if not query_engine:
                return {"error": "OCEL query engine not initialized"}

            stats = query_engine.get_statistics_by_object_type()

            if total_only:
                return {"total": len(stats)}

            response = ResponseBuilder.build_statistics_response(stats)
            return response.to_dict()

        except Exception as e:
            logger.error(f"Error in get_statistics_by_object_type: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def detect_anomalies(total_only: bool = False) -> Dict[str, Any]:
        """
        Detect anomalies in the event log (orphaned objects, broken references).

        Args:
            total_only: If True, return only the total count of anomalies instead of full data.

        Returns:
            Dict with detected anomalies and severity information.
        """
        try:
            query_engine = ocel_state.get("query_engine")
            if not query_engine:
                return {"error": "OCEL query engine not initialized"}

            anomalies = query_engine.detect_anomalies()

            if total_only:
                return {"total": len(anomalies)}

            response = ResponseBuilder.build_anomalies_response(anomalies)
            result = response.to_dict()

            cursor_store = ocel_state.get("cursor_store")
            if cursor_store:
                result = _paginate_response(result, "detect_anomalies", cursor_store)

            return result

        except Exception as e:
            logger.error(f"Error in detect_anomalies: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def find_orphaned_objects(total_only: bool = False) -> Dict[str, Any]:
        """
        Find objects that have no associated events.

        Args:
            total_only: If True, return only the total count of orphaned objects instead of full data.

        Returns:
            Dict with list of orphaned object IDs and statistics.
        """
        try:
            query_engine = ocel_state.get("query_engine")
            if not query_engine:
                return {"error": "OCEL query engine not initialized"}

            orphaned = query_engine.find_orphaned_objects()

            if total_only:
                return {"total": len(orphaned)}

            ocel_data = ocel_state.get("ocel_data")
            total_objects = len(ocel_data.objects) if ocel_data else 0

            response = ResponseBuilder.build_orphaned_response(
                orphaned, total_objects
            )
            result = response.to_dict()

            cursor_store = ocel_state.get("cursor_store")
            if cursor_store:
                result = _paginate_response(result, "find_orphaned_objects", cursor_store)

            return result

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
        query: str, top_k: int = 5, chunk_types: Optional[List[str]] = None, total_only: bool = False
    ) -> Dict[str, Any]:
        """
        Search the OCEL data using semantic/hybrid search.

        Args:
            query: Search query text.
            top_k: Number of results to return (default: 5).
            chunk_types: Optional list of chunk types to filter by. Valid values: ["event_types", "object_types", "events", "objects", "schema", "data"]. Use "schema" for event/object type definitions, "data" for actual events/objects.
            total_only: If True, return only the total count of results instead of full data.

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

            if total_only:
                return {"total": len(results)}

            # Format results inline (simpler format for LLM consumption)
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
        object_type: Optional[str] = None, limit: int = 10, total_only: bool = False
    ) -> Dict[str, Any]:
        """
        Extract and list process variants (activity sequences).

        Args:
            object_type: Optional object type filter.
            limit: Maximum number of variants to return (default: 10).
            total_only: If True, return only the total count of variants instead of full data.

        Returns:
            Dict with list of variants ordered by frequency.
        """
        try:
            mining_engine = ocel_state.get("mining_engine")
            if not mining_engine:
                return {"error": "Process mining engine not initialized"}

            variants = mining_engine.extract_process_variants(object_type, limit)

            if total_only:
                return {"total": len(variants)}

            response = ResponseBuilder.build_variants_response(variants, object_type)
            result = response.to_dict()

            cursor_store = ocel_state.get("cursor_store")
            if cursor_store:
                result = _paginate_response(result, "get_process_variants", cursor_store)

            return result

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
        object_type: Optional[str] = None, threshold_percentile: float = 75.0, total_only: bool = False
    ) -> Dict[str, Any]:
        """
        Detect performance bottlenecks in the process.

        Args:
            object_type: Optional object type filter.
            threshold_percentile: Percentile threshold for bottleneck detection (0-100, default: 75).
            total_only: If True, return only the total count of bottlenecks instead of full data.

        Returns:
            Dict with detected bottlenecks and affected activities.
        """
        try:
            mining_engine = ocel_state.get("mining_engine")
            if not mining_engine:
                return {"error": "Process mining engine not initialized"}

            bottlenecks = mining_engine.detect_bottlenecks(
                object_type, threshold_percentile
            )

            if total_only:
                count = len(bottlenecks) if isinstance(bottlenecks, list) else 1
                return {"total": count}

            response = ResponseBuilder.build_bottlenecks_response(
                bottlenecks
            )
            result = response.to_dict()

            cursor_store = ocel_state.get("cursor_store")
            if cursor_store:
                result = _paginate_response(result, "detect_bottlenecks", cursor_store)

            return result

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
    def analyze_object_interactions(total_only: bool = False) -> Dict[str, Any]:
        """
        Analyze interactions between different objects in the event log.

        Args:
            total_only: If True, return only the total count of interaction pairs instead of full data.

        Returns:
            Dict with object interaction patterns and co-occurrence statistics.
        """
        try:
            mining_engine = ocel_state.get("mining_engine")
            if not mining_engine:
                return {"error": "Process mining engine not initialized"}

            interactions = mining_engine.analyze_object_interactions()

            if total_only:
                count = len(interactions) if isinstance(interactions, list) else 1
                return {"total": count}

            response = ResponseBuilder.build_interactions_response(interactions)
            result = response.to_dict()

            cursor_store = ocel_state.get("cursor_store")
            if cursor_store:
                result = _paginate_response(result, "analyze_object_interactions", cursor_store)

            return result

        except Exception as e:
            logger.error(f"Error in analyze_object_interactions: {e}")
            return {"error": f"Internal error: {str(e)}"}

    @mcp.tool()
    @debug_log_tool
    def get_available_resource_attributes(total_only: bool = False) -> Dict[str, Any]:
        """
        Get list of available resource attributes for social network analysis.

        Args:
            total_only: If True, return only the total count of attributes instead of full data.

        Returns:
            Dict with available resource attribute names.
        """
        try:
            mining_engine = ocel_state.get("mining_engine")
            if not mining_engine:
                return {"error": "Process mining engine not initialized"}

            attributes = mining_engine.get_available_resource_attributes()

            if total_only:
                return {"total": len(attributes)}

            response = {
                "attributes": attributes,
                "total_count": len(attributes),
                "metadata": {
                    "generated_at": datetime.now().isoformat(),
                },
            }
            return response

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

    # =========================================================================
    # CURSOR / PAGINATION
    # =========================================================================

    @mcp.tool()
    @debug_log_tool
    def get_cursor_results(cursor_id: str, page: int = 1) -> Dict[str, Any]:
        """
        Retrieve a specific page of results from a previous query cursor.

        When a tool returns more results than fit in a single response, a
        cursor_id is included in the pagination metadata. Use this tool
        to fetch subsequent pages.

        Args:
            cursor_id: The cursor identifier returned by a previous tool call.
            page: Page number to retrieve (1-indexed, default: 1).

        Returns:
            Dict with items for the requested page and pagination metadata.
        """
        try:
            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            cursor_page = cursor_store.get_page(cursor_id, page)
            return cursor_page.to_dict()

        except KeyError as e:
            return {"error": str(e)}
        except ValueError as e:
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
            "generated_at": datetime.now().isoformat(),
            "page_size": constants.DEFAULT_PAGE_SIZE
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
