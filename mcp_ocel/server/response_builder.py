"""
MCP unified response builder.
Combines verifiable references, markdown, visualization, and metadata.
"""

from typing import Any, Dict, List, Optional

from .typing_ocel import UnifiedMCPResponse, EventReference, AnomalyReport
from shared.logger.logging_config import get_logger

logger = get_logger(__name__)

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
    def build_petri_net_response(
        pn_dict: Dict[str, Any],
        visualization: Optional[Dict[str, Any]] = None,
    ) -> UnifiedMCPResponse:
        """
        Builds a response for Petri net discovery.

        Args:
            pn_dict: Petri net info from ProcessMiningEngine.
            visualization: SVG/PNG visualization (optional).

        Returns:
            UnifiedMCPResponse.
        """
        logger.debug("Building Petri net discovery response")
        
        refs_list = [{
            "model_type": "Object-Centric Petri Net",
            "places": pn_dict.get("places", 0),
            "transitions": pn_dict.get("transitions", 0),
            "arcs": pn_dict.get("arcs", 0),
        }]
        
        summary = ResponseBuilder._build_petri_net_markdown(pn_dict)
        
        return UnifiedMCPResponse(
            references=refs_list,
            summary=summary,
            visualization=visualization,
            metadata=pn_dict,
        )
    
    @staticmethod
    def build_variants_response(
        variants: List[Dict[str, Any]],
        object_type: Optional[str] = None,
    ) -> UnifiedMCPResponse:
        """
        Builds a response for process variants.

        Args:
            variants: List of variants from ProcessMiningEngine.
            object_type: Object type filter used.

        Returns:
            UnifiedMCPResponse.
        """
        logger.debug(f"Building variants response ({len(variants)} variants)")
        
        refs_list = [
            {
                "variant_id": i + 1,
                "sequence": " → ".join(v.get("activity_sequence", [])),
                "frequency": v.get("frequency", 0),
                "sample_objects": v.get("sample_objects", v.get("sample_events", [])),
            }
            for i, v in enumerate(variants)
        ]
        
        summary = ResponseBuilder._build_variants_markdown(variants, object_type)
        
        metadata = {
            "total_variants": len(variants),
            "object_type_filter": object_type,
            "most_frequent": variants[0].get("frequency", 0) if variants else 0,
        }
        
        return UnifiedMCPResponse(
            references=refs_list,
            summary=summary,
            visualization=None,
            metadata=metadata,
        )
    
    @staticmethod
    def build_performance_response(
        metrics: Dict[str, Any],
    ) -> UnifiedMCPResponse:
        """
        Builds a response for performance metrics.
        All times are in SECONDS.

        Args:
            metrics: Performance metrics from ProcessMiningEngine.

        Returns:
            UnifiedMCPResponse.
        """
        logger.debug("Building performance metrics response")
        
        transitions = metrics.get("transitions", {})
        refs_list = [
            {
                "transition": trans,
                "avg_seconds": stats.get("avg_seconds", 0),
                "min_seconds": stats.get("min_seconds", 0),
                "max_seconds": stats.get("max_seconds", 0),
                "count": stats.get("count", 0),
            }
            for trans, stats in transitions.items()
        ]
        
        summary = ResponseBuilder._build_performance_markdown(metrics)
        
        metadata = {
            "time_unit": "seconds",
            "total_transitions": len(transitions),
            "total_observations": metrics.get("total_transitions_analyzed", 0),
        }
        
        return UnifiedMCPResponse(
            references=refs_list,
            summary=summary,
            visualization=None,
            metadata=metadata,
        )
    
    @staticmethod
    def build_bottlenecks_response(
        bottlenecks: Dict[str, Any],
    ) -> UnifiedMCPResponse:
        """
        Builds a response for detected bottlenecks.
        All times are in SECONDS.

        Args:
            bottlenecks: Bottleneck data from ProcessMiningEngine.

        Returns:
            UnifiedMCPResponse.
        """
        logger.debug("Building bottlenecks response")
        
        refs_list = bottlenecks.get("bottlenecks", [])
        summary = ResponseBuilder._build_bottlenecks_markdown(bottlenecks)
        
        metadata = {
            "time_unit": "seconds",
            "threshold_percentile": bottlenecks.get("threshold_percentile", 90),
            "threshold_seconds": bottlenecks.get("threshold_seconds", 0),
            "total_bottlenecks": len(refs_list),
        }
        
        return UnifiedMCPResponse(
            references=refs_list,
            summary=summary,
            visualization=None,
            metadata=metadata,
        )
    
    @staticmethod
    def build_conformance_response(
        conformance: Dict[str, Any],
    ) -> UnifiedMCPResponse:
        """
        Builds a response for conformance checking.

        Args:
            conformance: Conformance data from ProcessMiningEngine.

        Returns:
            UnifiedMCPResponse.
        """
        logger.debug("Building conformance response")
        
        refs_list = conformance.get("deviations", [])
        summary = ResponseBuilder._build_conformance_markdown(conformance)
        
        metadata = {
            "fitness_score": conformance.get("fitness_score", 0),
            "fitness_percentage": conformance.get("fitness_percentage", 0),
            "sample_size": conformance.get("sample_size", 0),
            "total_deviations": conformance.get("total_deviations", 0),
        }
        
        return UnifiedMCPResponse(
            references=refs_list,
            summary=summary,
            visualization=None,
            metadata=metadata,
        )
    
    @staticmethod
    def build_interactions_response(
        interactions: Dict[str, Any],
    ) -> UnifiedMCPResponse:
        """
        Builds a response for object interactions analysis.

        Args:
            interactions: Interactions data from ProcessMiningEngine.

        Returns:
            UnifiedMCPResponse.
        """
        logger.debug("Building interactions response")
        
        refs_list = interactions.get("top_interactions", [])
        summary = ResponseBuilder._build_interactions_markdown(interactions)
        
        metadata = {
            "object_types": interactions.get("object_types", []),
            "total_pairs": interactions.get("total_pairs_analyzed", 0),
        }
        
        return UnifiedMCPResponse(
            references=refs_list,
            summary=summary,
            visualization=None,
            metadata=metadata,
        )
    
    @staticmethod
    def build_social_network_response(
        network: Dict[str, Any],
    ) -> UnifiedMCPResponse:
        """
        Builds a response for social network discovery.

        Args:
            network: Network data from ProcessMiningEngine.

        Returns:
            UnifiedMCPResponse.
        """
        logger.debug("Building social network response")
        
        refs_list = network.get("edges", [])[:20]  # Top 20 edges
        summary = ResponseBuilder._build_social_network_markdown(network)
        
        metadata = {
            "total_nodes": network.get("total_nodes", 0),
            "total_edges": network.get("total_edges", 0),
            "resource_attribute": network.get("resource_attribute", ""),
        }
        
        return UnifiedMCPResponse(
            references=refs_list,
            summary=summary,
            visualization=None,
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
    def _build_petri_net_markdown(pn_dict: Dict[str, Any]) -> str:
        """Builds Petri net markdown summary."""
        lines = [
            "## Object-Centric Petri Net Discovered\n",
            f"**Places:** {pn_dict.get('places', 0)}\n",
            f"**Transitions:** {pn_dict.get('transitions', 0)}\n",
            f"**Arcs:** {pn_dict.get('arcs', 0)}\n",
        ]
        
        if pn_dict.get("initial_marking"):
            lines.append(f"\n**Initial Marking:** `{pn_dict['initial_marking']}`\n")
        if pn_dict.get("final_marking"):
            lines.append(f"**Final Marking:** `{pn_dict['final_marking']}`\n")
        
        return "".join(lines)
    
    @staticmethod
    def _build_variants_markdown(
        variants: List[Dict[str, Any]], object_type: Optional[str]
    ) -> str:
        """Builds variants markdown summary."""
        lines = [
            "## Process Variants\n",
            f"**Total Variants:** {len(variants)}\n",
        ]
        
        if object_type:
            lines.append(f"**Object Type Filter:** `{object_type}`\n")
        
        if variants:
            lines.append("\n### Top Variants by Frequency\n\n")
            lines.append("| Rank | Sequence | Frequency |\n")
            lines.append("|------|----------|----------|\n")
            
            for i, v in enumerate(variants[:10]):
                seq = " → ".join(v.get("activity_sequence", [])[:5])
                if len(v.get("activity_sequence", [])) > 5:
                    seq += " ..."
                freq = v.get("frequency", 0)
                lines.append(f"| {i+1} | {seq} | {freq} |\n")
        
        return "".join(lines)
    
    @staticmethod
    def _build_performance_markdown(metrics: Dict[str, Any]) -> str:
        """Builds performance metrics markdown summary."""
        lines = [
            "## Performance Metrics\n",
            f"**Time Unit:** seconds (SI)\n",
        ]
        
        transitions = metrics.get("transitions", {})
        if transitions:
            lines.append(f"**Total Transitions:** {len(transitions)}\n")
            lines.append(f"**Total Observations:** {metrics.get('total_transitions_analyzed', 0)}\n")
            
            # Sort by average time descending
            sorted_trans = sorted(
                transitions.items(),
                key=lambda x: x[1].get("avg_seconds", 0),
                reverse=True
            )[:10]
            
            lines.append("\n### Slowest Transitions (avg time)\n\n")
            lines.append("| Transition | Avg (s) | Min (s) | Max (s) | Count |\n")
            lines.append("|------------|---------|---------|---------|-------|\n")
            
            for trans, stats in sorted_trans:
                lines.append(
                    f"| {trans} | {stats.get('avg_seconds', 0):.1f} | "
                    f"{stats.get('min_seconds', 0):.1f} | {stats.get('max_seconds', 0):.1f} | "
                    f"{stats.get('count', 0)} |\n"
                )
        
        return "".join(lines)
    
    @staticmethod
    def _build_bottlenecks_markdown(bottlenecks: Dict[str, Any]) -> str:
        """Builds bottlenecks markdown summary."""
        bns = bottlenecks.get("bottlenecks", [])
        
        lines = [
            "## Detected Bottlenecks\n",
            f"**Threshold:** {bottlenecks.get('threshold_percentile', 90)}th percentile "
            f"({bottlenecks.get('threshold_seconds', 0):.1f} seconds)\n",
            f"**Bottlenecks Found:** {len(bns)}\n",
            f"**Time Unit:** seconds (SI)\n",
        ]
        
        if bns:
            lines.append("\n### Critical Transitions\n\n")
            lines.append("| Transition | Avg (s) | Max (s) | Severity |\n")
            lines.append("|------------|---------|---------|----------|\n")
            
            for bn in bns[:10]:
                severity_icon = "🔴" if bn.get("severity") == "high" else "⚠️"
                lines.append(
                    f"| {bn.get('transition', '')} | {bn.get('avg_seconds', 0):.1f} | "
                    f"{bn.get('max_seconds', 0):.1f} | {severity_icon} {bn.get('severity', '')} |\n"
                )
        else:
            lines.append("\n✓ No bottlenecks detected above threshold.\n")
        
        return "".join(lines)
    
    @staticmethod
    def _build_conformance_markdown(conformance: Dict[str, Any]) -> str:
        """Builds conformance markdown summary."""
        fitness = conformance.get("fitness_percentage", 0)
        
        lines = [
            "## Conformance Checking Results\n",
            f"**Fitness Score:** {conformance.get('fitness_score', 0):.4f} ({fitness:.1f}%)\n",
            f"**Sample Size:** {conformance.get('sample_size', 0)} traces\n",
            f"**Conformant Traces:** {conformance.get('conformant_traces', 0)}\n",
        ]
        
        deviations = conformance.get("deviations", [])
        if deviations:
            lines.append(f"\n### Deviations ({len(deviations)} shown)\n\n")
            for dev in deviations[:10]:
                lines.append(
                    f"- **{dev.get('object_id', '')}:** {dev.get('deviation', '')}\n"
                )
            
            total = conformance.get("total_deviations", 0)
            if total > len(deviations):
                lines.append(f"\n*... and {total - len(deviations)} more deviations*\n")
        else:
            lines.append("\n✓ All sampled traces conform to the model.\n")
        
        return "".join(lines)
    
    @staticmethod
    def _build_interactions_markdown(interactions: Dict[str, Any]) -> str:
        """Builds object interactions markdown summary."""
        top = interactions.get("top_interactions", [])
        
        lines = [
            "## Object Type Interactions\n",
            f"**Object Types:** {len(interactions.get('object_types', []))}\n",
            f"**Total Pairs Analyzed:** {interactions.get('total_pairs_analyzed', 0)}\n",
        ]
        
        if top:
            lines.append("\n### Strongest Co-occurrences\n\n")
            lines.append("| Type 1 | Type 2 | Co-occurrences |\n")
            lines.append("|--------|--------|----------------|\n")
            
            for pair in top[:10]:
                lines.append(
                    f"| {pair.get('type_1', '')} | {pair.get('type_2', '')} | "
                    f"{pair.get('co_occurrences', 0)} |\n"
                )
        
        return "".join(lines)
    
    @staticmethod
    def _build_social_network_markdown(network: Dict[str, Any]) -> str:
        """Builds social network markdown summary."""
        lines = [
            "## Social/Organizational Network\n",
            f"**Resource Attribute:** `{network.get('resource_attribute', '')}`\n",
            f"**Nodes (Resources):** {network.get('total_nodes', 0)}\n",
            f"**Edges (Handovers):** {network.get('total_edges', 0)}\n",
        ]
        
        edges = network.get("edges", [])
        if edges:
            lines.append("\n### Top Handover Relationships\n\n")
            lines.append("| From | To | Handovers |\n")
            lines.append("|------|----|-----------|\n")
            
            for edge in edges[:10]:
                lines.append(
                    f"| {edge.get('source', '')} | {edge.get('target', '')} | "
                    f"{edge.get('weight', 0)} |\n"
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
