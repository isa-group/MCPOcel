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
        Return all events that involve a specific object, ordered by timestamp.

        Each result is an event-reference dict:
          {event_id, activity, timestamp, involved_objects: [{object_id, object_type, role}]}.
        Use search_ocel or ocel://schema/objectTypes to discover valid object_ids first.
        With input_cursor_id the filter applies to that cursor subset instead of the full log.

        Args:
            object_id: Exact object identifier to trace (e.g. "pr-42"). Must exist in the log.
            input_cursor_id: cursor_id from a previous tool result to restrict the search scope.

        Returns:
            Dict with cursor_id for the matching event-reference items.
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
        Return all events whose timestamp falls within the given ISO 8601 window (both bounds inclusive).

        Prefer this over search_ocel for exact temporal filtering.
        Accepts "Z" UTC suffix (e.g. "2025-01-20T10:00:00Z") or numeric offset notation.
        With input_cursor_id the filter applies to that cursor subset instead of the full log.

        Args:
            start_datetime: Inclusive start in ISO 8601 format (e.g. "2025-01-20T00:00:00Z").
            end_datetime: Inclusive end in ISO 8601 format (e.g. "2025-01-20T23:59:59Z").
            input_cursor_id: cursor_id from a previous tool result to restrict the search scope.

        Returns:
            Dict with cursor_id for the matching event-reference items.
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
        Return object count and object-ID list grouped by object type.

        Response is keyed by object type name; each entry contains {count, objects: [ids]}.
        The type names returned here are the exact strings required by filter_by_object_type,
        discover_dfg, discover_petri_net, get_process_variants, get_performance_metrics, etc.
        Call this first to discover valid object-type values and their population sizes.

        Returns:
            Dict with one entry per object type: {object_type: {count, objects}}.
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
        Scan the event log for structural anomalies and return a cursor with all findings.

        Detects two anomaly types:
          - "orphaned_object": object referenced in relations but absent from all events.
          - "event_no_objects": event with no linked objects.
        Each result item has: {anomaly_type, severity ("low"|"medium"|"high"),
        affected_id, description, timestamp}.
        Use get_total_from_cursor_id to count anomalies cheaply without fetching all items.

        Returns:
            Dict with cursor_id for the detected anomaly items.
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
        Find objects not referenced by any event in the log.

        Each result item is {object_id, status: "orphaned"}.
        For a richer anomaly report (including events with no objects) use detect_anomalies instead.
        Prefer get_total_from_cursor_id over get_cursor_data when only the count is needed.

        Returns:
            Dict with cursor_id for the orphaned object items.
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
        List all registered MCP tools with their descriptions and parameter schemas.

        Call at session start or whenever it is unclear which tool to use.
        Returns each tool's name, single-line description, and inputSchema
        (type + description per parameter).

        Returns:
            Dict with tools list, total_count, and generation metadata.
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
        Full-text search across all OCEL content: attribute values, object IDs, activity names, and schema definitions.

        Use to locate events or objects by arbitrary text when the exact type or ID is unknown.
        For precise filtering by known activity or object type, prefer filter_by_event_type /
        filter_by_object_type (exact match, cursor-chainable, no relevance score noise).

        chunk_types values:
          - "event_types"  — only event-type labels
          - "object_types" — only object-type labels
          - "events"       — actual event instances with attribute values
          - "objects"      — actual object instances with attribute values
          - "schema"       — event/object type definitions and their declared attributes
          - "data"         — all events + objects with attribute values
        Omit chunk_types to search across all content.

        Args:
            query: Free-text search query.
            top_k: Maximum number of results to return (default: 5).
            chunk_types: Optional list of chunk type strings to restrict the search scope.

        Returns:
            Dict with query, total_results, and results list each containing {content, chunk_type, path, score, metadata}.
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
        Discover a Directly-Follows Graph (DFG) showing activity transition frequencies.

        Each edge in the response has {edge_id, source, target, frequency}.
        The response also includes start_activities: [{activity, frequency}].
        Results are cached; repeated calls for the same object_type are fast.
        Use object_type (exact name from get_statistics_by_object_type) to scope
        discovery to a single object perspective.

        Args:
            object_type: Optional exact object type name to restrict the DFG perspective.
            include_visualization: When True, includes an SVG string in the response.

        Returns:
            Dict with DFG edges, start_activities, and optional SVG visualization.
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
        Discover an Object-Centric Petri Net using the Inductive Miner algorithm.

        The response includes {total_places, total_transitions, total_arcs, nets_count, object_types}.
        Results are cached; repeated calls for the same object_type are fast.
        Inspect this before check_conformance to understand the reference model structure.
        Use object_type (exact name from get_statistics_by_object_type) to restrict
        the model to one object perspective.

        Args:
            object_type: Optional exact object type name to restrict the Petri net perspective.
            include_visualization: When True, includes an SVG string in the response.

        Returns:
            Dict with Petri net structure (total_places, total_transitions, total_arcs, nets_count).
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
        Extract the most frequent activity-sequence variants, ordered by descending frequency.

        A variant is a unique ordered sequence of activities followed by one object.
        Each result item has {variant_id, sequence (activities joined by " \u2192 "), frequency, sample_objects}.
        Use object_type to restrict extraction to one object perspective.

        Args:
            object_type: Optional exact object type name to restrict variant extraction.
            limit: Maximum number of variants to return, ordered by frequency (default: 10).

        Returns:
            Dict with cursor_id for the variant items.
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
        Calculate timing statistics for every activity transition in the process.

        All time values are in SECONDS — convert to minutes/hours/days for user-facing output.
        Returns per-transition stats keyed by "A \u2192 B":
          {count, avg_seconds, min_seconds, max_seconds, median_seconds, std_seconds}.
        Use detect_bottlenecks instead when only the slowest transitions are of interest.

        Args:
            object_type: Optional exact object type name to restrict metrics to one perspective.

        Returns:
            Dict with time_unit ("seconds"), total_transitions_analyzed, and a transitions map.
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
        Identify activity transitions whose average duration exceeds the given percentile threshold.

        Severity label: "high" when avg_seconds > threshold_seconds \u00d7 1.5, otherwise "medium".
        Each result item has {transition, avg_seconds, max_seconds, count, severity}.
        Response metadata includes {threshold_percentile, threshold_seconds, time_unit, total_transitions}.
        All time values are in SECONDS.

        Args:
            object_type: Optional exact object type name to restrict analysis to one perspective.
            threshold_percentile: Percentile (0-100) above which a transition is flagged (default: 75).

        Returns:
            Dict with cursor_id for the bottleneck items.
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
        Measure how closely observed traces conform to the Inductive-Miner Petri net model.

        Internally rediscovers the Petri net and replays sampled traces (up to 100 per object
        type, max 3 types). Returns at most 20 deviations.
        Response fields: {fitness_score (0-1), fitness_percentage, sample_size, conformant_traces,
        total_deviations, deviations: [{object_id, deviation, position}], model info}.
        Call discover_petri_net first to inspect the reference model before checking conformance.

        Args:
            object_type: Optional exact object type name to restrict conformance checking.

        Returns:
            Dict with fitness_score, fitness_percentage, deviations list, and model summary.
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
        Compute a co-occurrence matrix showing how often pairs of object types share the same event.

        An entry (type_A, type_B) counts events that involve at least one object of each type.
        Result items are {type_1, type_2, co_occurrences}, sorted by co_occurrences descending.
        Response metadata also contains co_occurrence_matrix and total_pairs_analyzed.

        Returns:
            Dict with cursor_id for the top object-type interaction pairs.
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
        List event attribute names that can be used as resource dimensions in discover_social_network.

        Always call this before discover_social_network to obtain valid resource_attribute values.
        Returns the exact attribute name strings to pass as the resource_attribute argument.

        Returns:
            Dict with attributes (list of strings) and total_count.
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
        Build a resource handover network showing collaboration between actors sharing events.

        Edges represent direct handover-of-work: actor A followed by actor B on the same object.
        Response is limited to the top 20 edges by weight. Each edge: {source, target, weight}.
        Response also contains {nodes, total_nodes, total_edges, resource_attribute}.
        If resource_attribute is not found, the response contains "error" and "available_attributes".
        Call get_available_resource_attributes first to obtain valid attribute names.

        Args:
            resource_attribute: Exact event attribute name identifying the resource (e.g. "actor").

        Returns:
            Dict with nodes list, top-20 edges, and network metrics.
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
        Return all events with exactly the given activity name (case-sensitive exact match).

        Prefer this over search_ocel for precise, non-fuzzy activity filtering.
        Valid activity names come from ocel://schema/eventTypes or the event_types list in ocel://info.
        Supports cursor chaining: pass input_cursor_id to filter within a prior result subset.

        Args:
            event_type: Exact activity name (case-sensitive) to filter for.
            input_cursor_id: cursor_id from a previous tool result to restrict the search scope.

        Returns:
            Dict with cursor_id for the matching event-reference items.
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
        Return all events that involve at least one object of the given type (case-sensitive exact match).

        Prefer this over search_ocel for precise, non-fuzzy object-type filtering.
        Valid object type names come from ocel://schema/objectTypes or get_statistics_by_object_type.
        Supports cursor chaining: pass input_cursor_id to filter within a prior result subset.

        Args:
            object_type: Exact object type name (case-sensitive) to filter for.
            input_cursor_id: cursor_id from a previous tool result to restrict the search scope.

        Returns:
            Dict with cursor_id for the matching event-reference items.
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

    @mcp.tool()
    @debug_log_tool
    def filter_by_attribute(
        attribute_name: str,
        attribute_value: str,
        match_type: str = "exact",
        target: str = "event",
        input_cursor_id: Optional[str] = None,
        case_sensitive: bool = True,
        max_results: int = 1000,
    ) -> Dict[str, Any]:
        """
        Filter events or objects by a top-level attribute value.

                Supports both `target` values: "event" or "object". Match modes:
                    - "exact": exact string/number equality
                    - "contains": substring match (string only)
                    - "regex": regular-expression match (Python regex)
                    - "numeric_range": numeric range with syntax `min:max` (either bound optional)

        Cursor-chaining: when `input_cursor_id` is provided, the filter is
        applied only to items in that cursor. For event cursors this will
        inspect the backing OCEL event rows; for object filtering it will
        inspect involved objects in the resolved events or the objects
        table when operating on the full log.

        Returns a `cursor_id` containing the matching references.
        """
        try:
            if target not in ("event", "object"):
                return {"error": "Invalid target; must be 'event' or 'object'"}

            cursor_store = ocel_state.get("cursor_store")
            if not cursor_store:
                return {"error": "Cursor store not available"}

            input_data = _resolve_input_data(ocel_state, input_cursor_id)

            refs = []

            # If input cursor provided, filter in-memory using the OCEL data
            if input_data is not None:
                ocel_data = ocel_state.get("ocel_data")
                if not ocel_data:
                    return {"error": "OCEL not initialized"}

                for ref in input_data:
                    # Event target: inspect event row for attribute
                    if target == "event":
                        eid = ref.get("event_id")
                        if not eid:
                            continue
                        # OCEL 2.0 event id column is `id`
                        rows = ocel_data.events[ocel_data.events["id"] == eid]
                        if rows.empty:
                            continue
                        val = rows.iloc[0].get(attribute_name)
                        if val is None:
                            continue
                        sval = str(val)
                        if match_type == "exact":
                            if case_sensitive:
                                match = sval == str(attribute_value)
                            else:
                                match = sval.lower() == str(attribute_value).lower()
                        elif match_type == "contains":
                            match = str(attribute_value) in sval if case_sensitive else str(attribute_value).lower() in sval.lower()
                        elif match_type == "regex":
                            import re as _re

                            try:
                                flags = 0 if case_sensitive else _re.IGNORECASE
                                match = bool(_re.search(attribute_value, sval, flags=flags))
                            except _re.error as err:
                                return {"error": f"Invalid regex pattern: {err}"}
                        elif match_type == "numeric_range":
                            # attribute_value expected as "min:max" where min or max can be empty
                            parts = str(attribute_value).split(":")
                            if len(parts) != 2:
                                return {"error": "numeric_range requires 'min:max' format"}
                            min_str, max_str = parts[0].strip(), parts[1].strip()
                            try:
                                val_num = float(sval)
                            except Exception:
                                continue
                            try:
                                min_val = float(min_str) if min_str != "" else None
                            except ValueError:
                                return {"error": "Invalid minimum value for numeric_range"}
                            try:
                                max_val = float(max_str) if max_str != "" else None
                            except ValueError:
                                return {"error": "Invalid maximum value for numeric_range"}

                            match = True
                            if min_val is not None and val_num < min_val:
                                match = False
                            if max_val is not None and val_num > max_val:
                                match = False
                            if not match:
                                continue
                        else:
                            return {"error": f"Unsupported match_type: {match_type}"}

                        if match:
                            refs.append(ref)

                    else:  # target == "object"
                        # Check involved objects first (if ref is an event-ref)
                        involved = ref.get("involved_objects") or []
                        matched = False
                        for obj in involved:
                            oid = obj.get("object_id")
                            if not oid:
                                continue
                            # OCEL 2.0 object id column is `id`
                            rows = ocel_data.objects[ocel_data.objects["id"] == oid]
                            if rows.empty:
                                continue
                            val = rows.iloc[0].get(attribute_name)
                            if val is None:
                                continue
                            sval = str(val)
                            if match_type == "exact":
                                if case_sensitive:
                                    match = sval == str(attribute_value)
                                else:
                                    match = sval.lower() == str(attribute_value).lower()
                            elif match_type == "contains":
                                match = str(attribute_value) in sval if case_sensitive else str(attribute_value).lower() in sval.lower()
                            elif match_type == "regex":
                                import re as _re

                                try:
                                    flags = 0 if case_sensitive else _re.IGNORECASE
                                    match = bool(_re.search(attribute_value, sval, flags=flags))
                                except _re.error as err:
                                    return {"error": f"Invalid regex pattern: {err}"}
                            elif match_type == "numeric_range":
                                parts = str(attribute_value).split(":")
                                if len(parts) != 2:
                                    return {"error": "numeric_range requires 'min:max' format"}
                                min_str, max_str = parts[0].strip(), parts[1].strip()
                                try:
                                    val_num = float(sval)
                                except Exception:
                                    continue
                                try:
                                    min_val = float(min_str) if min_str != "" else None
                                except ValueError:
                                    return {"error": "Invalid minimum value for numeric_range"}
                                try:
                                    max_val = float(max_str) if max_str != "" else None
                                except ValueError:
                                    return {"error": "Invalid maximum value for numeric_range"}

                                match = True
                                if min_val is not None and val_num < min_val:
                                    match = False
                                if max_val is not None and val_num > max_val:
                                    match = False
                                if not match:
                                    continue
                            else:
                                return {"error": f"Unsupported match_type: {match_type}"}

                            if match:
                                matched = True
                                break

                        if matched:
                            refs.append(ref)

                # Enforce max_results
                if len(refs) > max_results:
                    refs = refs[:max_results]

            else:
                # No input cursor: delegate to query_engine for efficient filtering
                query_engine = ocel_state.get("query_engine")
                if not query_engine:
                    return {"error": "OCEL query engine not initialized"}

                # Protect expensive operations with the OCEL lock if present
                # Pre-validate regex patterns to provide a clear error before
                # delegating to the potentially external/compiled query engine.
                if match_type == "regex":
                    try:
                        import re as _re

                        flags = 0 if case_sensitive else _re.IGNORECASE
                        _re.compile(attribute_value, flags=flags)
                    except _re.error as err:
                        return {"error": f"Invalid regex pattern: {err}"}

                # Pre-validate numeric_range format and bounds to provide a
                # consistent error message before delegating to query_engine.
                if match_type == "numeric_range":
                    parts = str(attribute_value).split(":")
                    if len(parts) != 2:
                        return {"error": "numeric_range requires 'min:max' format"}
                    min_str, max_str = parts[0].strip(), parts[1].strip()
                    try:
                        if min_str != "":
                            float(min_str)
                    except ValueError:
                        return {"error": "Invalid minimum value for numeric_range"}
                    try:
                        if max_str != "":
                            float(max_str)
                    except ValueError:
                        return {"error": "Invalid maximum value for numeric_range"}

                if ocel_lock:
                    with ocel_lock:
                        if target == "event":
                            references = query_engine.get_events_by_attribute(
                                attribute_name,
                                attribute_value,
                                match_type=match_type,
                                case_sensitive=case_sensitive,
                                max_results=max_results,
                            )
                            refs = [r.to_dict() for r in references]
                        else:
                            references = query_engine.get_objects_by_attribute(
                                attribute_name,
                                attribute_value,
                                match_type=match_type,
                                case_sensitive=case_sensitive,
                                max_results=max_results,
                            )
                            refs = [r.to_dict() for r in references]
                else:
                    if target == "event":
                        references = query_engine.get_events_by_attribute(
                            attribute_name,
                            attribute_value,
                            match_type=match_type,
                            case_sensitive=case_sensitive,
                            max_results=max_results,
                        )
                        refs = [r.to_dict() for r in references]
                    else:
                        references = query_engine.get_objects_by_attribute(
                            attribute_name,
                            attribute_value,
                            match_type=match_type,
                            case_sensitive=case_sensitive,
                            max_results=max_results,
                        )
                        refs = [r.to_dict() for r in references]

            cursor_id = cursor_store.create_cursor("filter_by_attribute", refs)
            return {"cursor_id": cursor_id}

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error in filter_by_attribute: {e}")
            return {"error": f"Internal error: {str(e)}"}

    # =========================================================================
    # CURSOR INSPECTION & SET OPERATIONS
    # =========================================================================

    @mcp.tool()
    @debug_log_tool
    def get_total_from_cursor_id(cursor_id: str) -> Dict[str, Any]:
        """
        Return the item count of a cursor without loading any data.

        Use this instead of get_cursor_data when only a count is needed.
        For a richer summary (activity types, object types, time range)
        use get_summary_from_cursor_id instead.

        Args:
            cursor_id: The cursor identifier returned by a previous tool call.

        Returns:
            Dict with cursor_id and total (integer item count).
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
        Return the temporal bounds of an event cursor without loading any data.

        Returns {cursor_id, start (ISO 8601), end (ISO 8601), duration_seconds}.
        Only works for event-reference cursors (produced by filter_by_event_type,
        query_events_by_timerange, trace_object_lifecycle, etc.).
        Raises an error for non-event cursors (e.g. find_orphaned_objects).
        Use before further time-window decomposition to know the active time span.

        Args:
            cursor_id: The cursor identifier returned by a previous tool call.

        Returns:
            Dict with cursor_id, start, end (ISO 8601 strings), and duration_seconds.
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
        Compute the intersection of two event cursors — keeps only events present in BOTH.

        Deduplicates on event_id. Does not load any data into the LLM context.
        Both cursors must be event-reference cursors (from event-filtering tools).
        Non-event cursors (e.g. find_orphaned_objects) are not supported.
        Use to combine two independent parallel filters without fetching intermediate results.

        Args:
            cursor_id_1: First event-reference cursor identifier.
            cursor_id_2: Second event-reference cursor identifier.

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
        Compute the union of two event cursors — all events from either, deduplicated by event_id.

        Does not load any data into the LLM context.
        Both cursors must be event-reference cursors (from event-filtering tools).
        Non-event cursors (e.g. find_orphaned_objects) are not supported.
        Use to merge results from parallel filter paths before inspection or fetch.

        Args:
            cursor_id_1: First event-reference cursor identifier.
            cursor_id_2: Second event-reference cursor identifier.

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
        Return a lightweight summary of a cursor's contents without loading all items.

        Reports: total item count, distinct activity_types, distinct object_types,
        time_start and time_end (ISO 8601).
        Activity/object/time fields are only populated for event-reference cursors
        (from event-filtering tools); other cursor types return those fields as None.
        Call this before get_cursor_data to characterise a subset and decide whether to fetch.

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
    def get_cursor_data(cursor_id: str) -> Dict[str, Any]:
        """
        Fetch ALL items stored in a cursor — USE ONLY for the final subset to present to the user.

        This loads the full dataset into context; prefer cheaper inspection tools first:
          - get_total_from_cursor_id    → count only
          - get_timerange_by_cursor_id  → temporal bounds only
          - get_summary_from_cursor_id  → count + types + time range

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
            logger.error(f"Error in get_cursor_data: {e}")
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

            events_attributes = {
                et: ocel_config.attribute_names.get(et, [])
                for et in ocel_config.event_types
            }
            object_attributes = {
                ot: ocel_config.attribute_names.get(ot, [])
                for ot in ocel_config.object_types
            }

            info = {
                "file_path": ocel_path,
                "event_types": list(ocel_config.event_types),
                "object_types": list(ocel_config.object_types),
                "total_events": len(ocel_data.events),
                "total_objects": len(ocel_data.objects),
                "total_relations": len(ocel_data.relations),
                "start_date": start_date,
                "end_date": end_date,
                "events_attributes": events_attributes,
                "object_attributes": object_attributes,
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
