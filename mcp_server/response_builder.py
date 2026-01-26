"""
MCP unified response builder.
Combines verifiable references, markdown, visualization, and metadata.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime

from . import logger
from .typing_ocel import UnifiedMCPResponse, EventReference, AnomalyReport


class ResponseBuilder:
    """Builds unified responses with references, summary, and visualization."""
    
    @staticmethod
    def build_lifecycle_response(
        object_id: str,
        references: List[EventReference],
        visualization: Optional[Dict[str, Any]] = None,
    ) -> UnifiedMCPResponse:
        """
        Builds a response for an object's lifecycle.

        Args:
            object_id: Object identifier.
            references: List of EventReference.
            visualization: Visualization dict (optional).

        Returns:
            UnifiedMCPResponse.
        """
        logger.debug(f"Building lifecycle response for {object_id}")
        
        refs_list = [ref.to_dict() for ref in references]
        summary = ResponseBuilder._build_lifecycle_markdown(object_id, references)
        metadata = {
            "object_id": object_id,
            "total_events": len(references),
            "event_types": list(set(ref.activity for ref in references)),
            "time_span": ResponseBuilder._calculate_timespan(references),
        }
        
        return UnifiedMCPResponse(
            references=refs_list,
            summary=summary,
            visualization=visualization,
            metadata=metadata,
        )
    
    @staticmethod
    def build_timerange_response(
        start_datetime: str,
        end_datetime: str,
        references: List[EventReference],
        visualization: Optional[Dict[str, Any]] = None,
    ) -> UnifiedMCPResponse:
        """
        Builds a response for a time-range query.

        Args:
            start_datetime: Start datetime.
            end_datetime: End datetime.
            references: List of EventReference.
            visualization: Visualization dict (optional).

        Returns:
            UnifiedMCPResponse.
        """
        logger.debug(f"Building timerange response {start_datetime} to {end_datetime}")
        
        refs_list = [ref.to_dict() for ref in references]
        
        summary = ResponseBuilder._build_timerange_markdown(
            start_datetime, end_datetime, references
        )
        
        metadata = {
            "start_datetime": start_datetime,
            "end_datetime": end_datetime,
            "total_events": len(references),
            "event_types": list(set(ref.activity for ref in references)),
            "objects_involved": len(set(
                obj.object_id for ref in references for obj in ref.involved_objects
            )),
        }
        
        return UnifiedMCPResponse(
            references=refs_list,
            summary=summary,
            visualization=visualization,
            metadata=metadata,
        )
    
    @staticmethod
    def build_statistics_response(
        stats: Dict[str, Any],
        visualization: Optional[Dict[str, Any]] = None,
    ) -> UnifiedMCPResponse:
        """
        Builds a response for statistics.

        Args:
            stats: Statistics dict.
            visualization: Visualization dict (optional).

        Returns:
            UnifiedMCPResponse.
        """
        logger.debug("Building statistics response")
        
        refs_list = ResponseBuilder._convert_stats_to_refs(stats)
        
        summary = ResponseBuilder._build_statistics_markdown(stats)
        
        return UnifiedMCPResponse(
            references=refs_list,
            summary=summary,
            visualization=visualization,
            metadata=stats,
        )
    
    @staticmethod
    def build_anomalies_response(
        anomalies: List[AnomalyReport],
        visualization: Optional[Dict[str, Any]] = None,
    ) -> UnifiedMCPResponse:
        """
        Builds a response for detected anomalies.

        Args:
            anomalies: List of AnomalyReport.
            visualization: Visualization dict (optional).

        Returns:
            UnifiedMCPResponse.
        """
        logger.debug(f"Building anomalies response ({len(anomalies)} detected)")
        
        refs_list = [anom.to_dict() for anom in anomalies]
        
        summary = ResponseBuilder._build_anomalies_markdown(anomalies)
        
        by_type = {}
        for anom in anomalies:
            if anom.anomaly_type not in by_type:
                by_type[anom.anomaly_type] = 0
            by_type[anom.anomaly_type] += 1
        
        metadata = {
            "total_anomalies": len(anomalies),
            "by_type": by_type,
            "severity_levels": list(set(anom.severity for anom in anomalies)),
        }
        
        return UnifiedMCPResponse(
            references=refs_list,
            summary=summary,
            visualization=visualization,
            metadata=metadata,
        )
    
    @staticmethod
    def build_orphaned_response(
        orphaned_objects: List[str],
        total_objects: int,
        visualization: Optional[Dict[str, Any]] = None,
    ) -> UnifiedMCPResponse:
        """
        Builds a response for orphaned objects.

        Args:
            orphaned_objects: List of orphaned object IDs.
            total_objects: Total objects in the OCEL.
            visualization: Visualization dict (optional).

        Returns:
            UnifiedMCPResponse.
        """
        logger.debug(f"Building orphaned objects response ({len(orphaned_objects)})")
        
        refs_list = [
            {"object_id": obj_id, "status": "orphaned"}
            for obj_id in orphaned_objects
        ]
        
        summary = ResponseBuilder._build_orphaned_markdown(orphaned_objects, total_objects)
        
        metadata = {
            "orphaned_count": len(orphaned_objects),
            "total_objects": total_objects,
            "orphaned_percentage": (len(orphaned_objects) / total_objects * 100) if total_objects > 0 else 0,
        }
        
        return UnifiedMCPResponse(
            references=refs_list,
            summary=summary,
            visualization=visualization,
            metadata=metadata,
        )
    
    @staticmethod
    def build_dfg_response(
        dfg_dict: Dict[str, Any],
        visualization: Optional[Dict[str, Any]] = None,
    ) -> UnifiedMCPResponse:
        """
        Builds a response for DFG discovery.

        Args:
            dfg_dict: DFG obtained from ProcessMiningEngine.
            visualization: SVG/PNG visualization (recommended).

        Returns:
            UnifiedMCPResponse.
        """
        logger.debug("Building DFG discovery response")
        
        refs_list = [
            {
                "edge_id": f"{edge['source']}->{edge['target']}",
                "source": edge["source"],
                "target": edge["target"],
                "frequency": edge.get("frequency", 1),
            }
            for edge in dfg_dict.get("edges", [])
        ]
        
        summary = ResponseBuilder._build_dfg_markdown(dfg_dict)
        
        metadata = {
            "edges_count": len(dfg_dict.get("edges", [])),
            "start_activities": dfg_dict.get("start_activities", []),
            "unique_activities": len(set(
                edge["source"] for edge in dfg_dict.get("edges", [])
            ).union(set(
                edge["target"] for edge in dfg_dict.get("edges", [])
            ))),
        }
        
        return UnifiedMCPResponse(
            references=refs_list,
            summary=summary,
            visualization=visualization,
            metadata=metadata,
        )
    
    @staticmethod
    def _build_lifecycle_markdown(object_id: str, references: List[EventReference]) -> str:
        """Builds lifecycle markdown summary."""
        lines = [
            f"## Object Lifecycle\n",
            f"**ID:** `{object_id}`\n",
            f"**Total Events:** {len(references)}\n",
        ]
        
        if references:
            start_ts = references[0].timestamp
            end_ts = references[-1].timestamp
            lines.append(f"**Period:** {start_ts} → {end_ts}\n")
            
            activities = list(set(ref.activity for ref in references))
            lines.append(f"**Activities:** {', '.join(f'`{a}`' for a in activities)}\n")
            
            lines.append("\n### Related Events\n\n")
            lines.append("| Event | Activity | Timestamp | Involved Objects |\n")
            lines.append("|-------|----------|-----------|------------------|\n")
            
            for ref in references[:10]:  # First 10
                objs_str = ", ".join(f"`{o.object_id}`" for o in ref.involved_objects[:3])
                lines.append(
                    f"| {ref.event_id} | {ref.activity} | {ref.timestamp} | {objs_str} |\n"
                )
            
            if len(references) > 10:
                lines.append(f"\n*... and {len(references) - 10} more events*\n")
        
        return "".join(lines)
    
    @staticmethod
    def _build_timerange_markdown(
        start: str, end: str, references: List[EventReference]
    ) -> str:
        """Builds time-range markdown summary."""
        lines = [
            f"## Events in Time Range\n",
            f"**Period:** {start} to {end}\n",
            f"**Total Events:** {len(references)}\n",
        ]
        
        if references:
            activities = list(set(ref.activity for ref in references))
            lines.append(f"**Activity Types:** {len(activities)}\n")
            lines.append(f"**Activities:** {', '.join(f'`{a}`' for a in activities)}\n")
            
            activity_counts = {}
            for ref in references:
                activity_counts[ref.activity] = activity_counts.get(ref.activity, 0) + 1
            
            lines.append("\n### Event Distribution\n\n")
            for activity, count in sorted(activity_counts.items(), key=lambda x: -x[1]):
                lines.append(f"- **{activity}:** {count} event(s)\n")
        
        return "".join(lines)
    
    @staticmethod
    def _build_statistics_markdown(stats: Dict[str, Any]) -> str:
        """Builds statistics markdown summary."""
        lines = [
            "## OCEL Statistics\n",
        ]
        
        for obj_type, type_stats in stats.items():
            if isinstance(type_stats, dict) and "count" in type_stats:
                lines.append(f"- **{obj_type}:** {type_stats['count']} object(s)\n")
        
        return "".join(lines)
    
    @staticmethod
    def _build_anomalies_markdown(anomalies: List[AnomalyReport]) -> str:
        """Builds anomalies markdown summary."""
        lines = [
            f"## Detected Anomalies ({len(anomalies)})\n",
        ]
        
        if not anomalies:
            lines.append("✓ No anomalies detected.\n")
        else:
            lines.append("\n### By Type\n\n")
            
            by_type = {}
            for anom in anomalies:
                if anom.anomaly_type not in by_type:
                    by_type[anom.anomaly_type] = []
                by_type[anom.anomaly_type].append(anom)
            
            for anom_type, anoms in sorted(by_type.items()):
                lines.append(f"#### {anom_type} ({len(anoms)})\n\n")
                for anom in anoms[:5]:
                    severity_emoji = {"low": "⚠️", "medium": "⚠️⚠️", "high": "🔴"}
                    lines.append(
                        f"{severity_emoji.get(anom.severity, '')} "
                        f"**{anom.affected_id}:** {anom.description}\n"
                    )
                if len(anoms) > 5:
                    lines.append(f"\n*... and {len(anoms) - 5} more*\n")
        
        return "".join(lines)
    
    @staticmethod
    def _build_orphaned_markdown(orphaned: List[str], total: int) -> str:
        """Builds orphaned-objects markdown summary."""
        percentage = (len(orphaned) / total * 100) if total > 0 else 0
        
        lines = [
            f"## Orphaned Objects\n",
            f"**Total:** {len(orphaned)} of {total} object(s) ({percentage:.1f}%)\n",
        ]
        
        if orphaned:
            lines.append("\n### Object IDs\n\n")
            for obj_id in orphaned[:20]:
                lines.append(f"- `{obj_id}`\n")
            
            if len(orphaned) > 20:
                lines.append(f"\n*... and {len(orphaned) - 20} more*\n")
        
        return "".join(lines)
    
    @staticmethod
    def _build_dfg_markdown(dfg_dict: Dict[str, Any]) -> str:
        """Builds DFG markdown summary."""
        edges = dfg_dict.get("edges", [])
        
        lines = [
            "## Directly Follows Graph (DFG) Discovered\n",
            f"**Edges:** {len(edges)}\n",
        ]
        
        if edges:
            activities = set()
            for edge in edges:
                activities.add(edge["source"])
                activities.add(edge["target"])
            
            lines.append(f"**Unique Activities:** {len(activities)}\n")
            
            top_edges = sorted(edges, key=lambda x: -x.get("frequency", 1))[:5]
            
            lines.append("\n### Most Frequent Relationships\n\n")
            for edge in top_edges:
                lines.append(
                    f"- `{edge['source']}` → `{edge['target']}` "
                    f"({edge.get('frequency', 1)} times)\n"
                )
        
        return "".join(lines)
    
    @staticmethod
    def _calculate_timespan(references: List[EventReference]) -> Dict[str, str]:
        """Calculates the time span of the events."""
        if not references:
            return {}
        
        return {
            "start": references[0].timestamp,
            "end": references[-1].timestamp,
            "duration_description": "Span between first and last event",
        }
    
    @staticmethod
    def _convert_stats_to_refs(stats: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Converts statistics to a reference-like structure."""
        refs = []
        for obj_type, type_stats in stats.items():
            if isinstance(type_stats, dict) and "count" in type_stats:
                refs.append({
                    "object_type": obj_type,
                    "count": type_stats["count"],
                    "type": "statistic",
                })
        return refs
