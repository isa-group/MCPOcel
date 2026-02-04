"""
PM4PY wrapper for domain-agnostic process mining.
Exposes: DFG discovery, Petri net discovery, variants, and statistics.
"""

from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple
import hashlib

from shared.logger.logging_config import get_logger
from .typing_ocel import (
    OCELData,
    DFGDict,
    PetriNetDict,
    PerformanceMetricsDict,
    BottleneckResultDict,
    ConformanceResultDict,
    ObjectInteractionsResultDict,
    VariantDict,
    SocialNetworkResultDict,
    OCELStatsDict,
)

logger = get_logger(__name__)

try:
    import pm4py
except ImportError:
    logger.error("PM4PY not installed. Install with: pip install pm4py")
    pm4py = None


class ModelCache:
    """LRU cache for discovered process models (DFG, Petri Net)."""
    
    def __init__(self, maxsize: int = 32):
        """
        Initialize model cache.
        
        Args:
            maxsize: Maximum number of models to cache (default: 32)
        """
        self.maxsize = maxsize
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._hits = 0
        self._misses = 0
    
    def _make_key(self, model_type: str, object_type: Optional[str] = None) -> str:
        """Generate cache key from model parameters."""
        key_data = f"{model_type}:{object_type or 'all'}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:16]
    
    def get(self, model_type: str, object_type: Optional[str] = None) -> Optional[Any]:
        """Get cached model if available."""
        key = self._make_key(model_type, object_type)
        if key in self._cache:
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hits += 1
            logger.debug(f"Cache hit for {model_type} (object_type={object_type})")
            return self._cache[key]
        self._misses += 1
        return None
    
    def set(self, model_type: str, object_type: Optional[str], value: Any) -> None:
        """Store model in cache."""
        key = self._make_key(model_type, object_type)
        
        # Remove oldest if at capacity
        if len(self._cache) >= self.maxsize:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            logger.debug(f"Cache evicted oldest entry")
        
        self._cache[key] = value
        self._cache.move_to_end(key)
        logger.debug(f"Cached {model_type} (object_type={object_type})")
    
    def invalidate(self) -> None:
        """Clear all cached models (call when OCEL changes)."""
        self._cache.clear()
        logger.info("Model cache invalidated")
    
    def stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        return {
            "size": len(self._cache),
            "maxsize": self.maxsize,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / (self._hits + self._misses) if (self._hits + self._misses) > 0 else 0,
        }


# Global model cache instance
_model_cache = ModelCache(maxsize=32)


class ProcessMiningEngine:
    """Domain-agnostic process mining wrapper with PM4PY."""
    
    ocel_data: OCELData
    
    def __init__(self, ocel_data: OCELData) -> None:
        """
        Initializes the process mining engine.

        Args:
            ocel_data: Loaded OCEL (PM4PY object).
        """
        if pm4py is None:
            raise ImportError("PM4PY is not available")
        
        self.ocel_data = ocel_data
    
    def discover_dfg(
        self, object_type: Optional[str] = None, use_cache: bool = True
    ) -> Tuple[DFGDict, Dict[str, Any]]:
        """
        Discovers an object-centric Directly Follows Graph (DFG).

        Results are cached by (object_type) to avoid redundant PM4PY calls.
        Use `use_cache=False` to force recomputation.

        Args:
            object_type: Object type filter (None = all).
            use_cache: Whether to use cached results (default: True).

        Returns:
            Tuple of (DFGDict with edges and start activities, frequency dict).
        """
        # Check cache first
        if use_cache:
            cached = _model_cache.get("dfg", object_type)
            if cached is not None:
                return cached
        
        logger.info(f"Discovering OC-DFG (object_type={object_type})")
        result = self._discover_dfg(object_type)
        
        # Store in cache
        if use_cache and result[0]:
            _model_cache.set("dfg", object_type, result)
        
        return result
    
    def _discover_dfg(
        self, object_type: Optional[str] = None
    ) -> Tuple[Dict, Dict]:
        """Discovers an Object-Centric DFG using PM4PY."""
        try:
            if object_type:
                filtered = pm4py.filter_ocel_object_types(
                    self.ocel_data, [object_type]
                )
                ocdfg = pm4py.discover_ocdfg(filtered)
            else:
                ocdfg = pm4py.discover_ocdfg(self.ocel_data)
            
            # Extract edges from ocdfg result
            # edges structure: {"event_couples": {obj_type: {(src,tgt): set}}, "unique_objects": {...}, ...}
            edges_data = ocdfg.get("edges", {})
            event_couples = edges_data.get("event_couples", {})
            
            # start_activities structure: {"events": {obj_type: {activity: set_of_events}}, ...}
            start_activities_raw = ocdfg.get("start_activities", {})
            
            # Aggregate edge frequencies across all object types
            # Structure: event_couples[obj_type][(src_act, tgt_act)] = set of event pairs
            edge_counts: Dict[Tuple[str, str], int] = {}
            
            for _, edges_dict in event_couples.items():
                if isinstance(edges_dict, dict):
                    for edge_tuple, event_set in edges_dict.items():
                        count = len(event_set) if isinstance(event_set, set) else 1
                        edge_counts[edge_tuple] = edge_counts.get(edge_tuple, 0) + count
            
            edges_list = []
            for (src, tgt), freq in edge_counts.items():
                edges_list.append({
                    "source": str(src),
                    "target": str(tgt),
                    "frequency": freq,
                })
            
            # Calculate start activity frequencies from events sub-dict
            # Structure: {"events": {obj_type: {activity: set_of_event_ids}}}
            start_list = []
            start_events = start_activities_raw.get("events", {})
            activity_counts: Dict[str, int] = {}
            
            for _, activities_dict in start_events.items():
                if isinstance(activities_dict, dict):
                    for activity, event_set in activities_dict.items():
                        count = len(event_set) if isinstance(event_set, set) else 1
                        activity_counts[activity] = activity_counts.get(activity, 0) + count
            
            for activity, freq in activity_counts.items():
                start_list.append({
                    "activity": str(activity),
                    "frequency": freq,
                })
            
            dfg_dict = {
                "edges": edges_list,
                "start_activities": start_list,
            }
            
            logger.info(f"DFG discovered: {len(dfg_dict['edges'])} edges")
            return dfg_dict, {}
        
        except Exception as e:
            logger.error(f"Error discovering DFG: {e}")
            raise
    
    def discover_petri_net(
        self, object_type: Optional[str] = None, use_cache: bool = True
    ) -> PetriNetDict:
        """
        Discovers an Object-Centric Petri Net (OC-PN).

        Results are cached by (object_type) to avoid redundant PM4PY calls.
        Use `use_cache=False` to force recomputation.

        Args:
            object_type: Object type filter (None = all).
            use_cache: Whether to use cached results (default: True).

        Returns:
            PetriNetDict with places, transitions, arcs, and markings.
        """
        # Check cache first
        if use_cache:
            cached = _model_cache.get("petri_net", object_type)
            if cached is not None:
                return cached
        
        logger.info(f"Discovering OC-PN (object_type={object_type})")
        result = self._discover_petri_net(object_type)
        
        # Store in cache
        if use_cache and result:
            _model_cache.set("petri_net", object_type, result)
        
        return result
    
    def _discover_petri_net(
        self, object_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Discovers an Object-Centric Petri Net using PM4PY."""
        try:
            if object_type:
                filtered = pm4py.filter_ocel_object_types(
                    self.ocel_data, [object_type]
                )
                oc_pn = pm4py.discover_oc_petri_net(filtered)
            else:
                oc_pn = pm4py.discover_oc_petri_net(self.ocel_data)
            
            # Extract petri nets per object type
            petri_nets = oc_pn.get("petri_nets", {})
            total_places = 0
            total_transitions = 0
            total_arcs = 0
            
            for _, (net, _, _) in petri_nets.items():
                total_places += len(net.places)
                total_transitions += len(net.transitions)
                total_arcs += len(net.arcs)
            
            pn_dict = {
                "object_types": list(petri_nets.keys()),
                "total_places": total_places,
                "total_transitions": total_transitions,
                "total_arcs": total_arcs,
                "nets_count": len(petri_nets),
            }
            
            logger.info(f"Petri net discovered: {pn_dict['total_places']} places, "
                       f"{pn_dict['total_transitions']} transitions")
            return pn_dict
        
        except Exception as e:
            logger.error(f"Error discovering Petri net: {e}")
            raise
    
    def extract_process_variants(
        self, object_type: Optional[str] = None, limit: int = 10
    ) -> List[VariantDict]:
        """
        Extracts process variants (activity sequences).

        This method does NOT cache results as variant extraction is lightweight.

        Args:
            object_type: Object type filter.
            limit: Maximum variants to return (top-N) to keep responses manageable; defaults to 10.

        Returns:
            List of VariantDict ordered by frequency.
        """
        logger.info(f"Extracting process variants (limit={limit})")
        
        ocel = self.ocel_data
        if object_type:
            ocel = pm4py.filter_ocel_object_types(ocel, [object_type])
        
        variants: Dict[str, Dict[str, Any]] = {}
        
        for _, event in ocel.events.iterrows():
            event_id = str(event.get("ocel:eid", ""))
            activity = str(event.get("ocel:activity", "unknown"))
            
            # TODO: Improve to full object-centric sequences
            if activity not in variants:
                variants[activity] = {
                    "activity_sequence": [activity],
                    "frequency": 0,
                    "sample_events": [],
                }
            
            variants[activity]["frequency"] += 1
            # Limit samples to 3 IDs to illustrate without inflating the payload.
            if len(variants[activity]["sample_events"]) < 3:
                variants[activity]["sample_events"].append(event_id)
        
        sorted_variants = sorted(
            variants.values(),
            key=lambda x: x["frequency"],
            reverse=True,
        )[:limit]
        
        logger.info(f"Variants extracted: {len(sorted_variants)}")
        return sorted_variants
    
    def get_ocel_statistics(self) -> OCELStatsDict:
        """
        Retrieves general OCEL statistics.

        This method does NOT cache results as it accesses DataFrame properties directly.

        Returns:
            OCELStatsDict with totals for events, objects, types, and distributions.
        """
        logger.debug("Fetching OCEL statistics")
        try:
            stats = {
                "total_events": len(self.ocel_data.events),
                "total_objects": len(self.ocel_data.objects),
                "object_types": self.ocel_data.objects["ocel:type"].nunique(),
                "event_types": self.ocel_data.events["ocel:activity"].nunique(),
            }
            logger.info("OCEL statistics obtained")
            return stats
        except Exception as e:
            logger.error(f"Error obtaining PM4PY statistics: {e}")
            return {}
    
    # ========================================================================
    # NEW METHODS: Object-Centric Variants, Performance, Conformance
    # ========================================================================
    
    def extract_object_centric_variants(
        self, object_type: Optional[str] = None, limit: int = 10
    ) -> List[VariantDict]:
        """
        Extract true object-centric process variants.
        Uses PM4PY's ocel_flattening to convert OCEL to traditional log per object type,
        then extracts variants using get_variants.

        Args:
            object_type: Filter by object type (optional).
            limit: Maximum variants to return.

        Returns:
            List of VariantDict with sequence, frequency, and sample objects.
        """
        logger.info(f"Extracting object-centric variants (object_type={object_type}, limit={limit})")
        
        try:
            ocel = self.ocel_data
            
            # Get object types to process
            if object_type:
                object_types = [object_type]
            else:
                object_types = pm4py.ocel_get_object_types(ocel)
            
            # Aggregate variants across all object types
            variants_map: Dict[tuple, Dict] = {}
            
            for ot in object_types:
                try:
                    # Flatten OCEL to traditional log for this object type
                    flat_log = pm4py.ocel_flattening(ocel, ot)
                    
                    # Get variants using PM4PY's native function
                    pm4py_variants = pm4py.get_variants(flat_log)
                    
                    for sequence, count in pm4py_variants.items():
                        if sequence not in variants_map:
                            variants_map[sequence] = {
                                "activity_sequence": list(sequence),
                                "frequency": 0,
                                "object_types": [],
                            }
                        variants_map[sequence]["frequency"] += count
                        if ot not in variants_map[sequence]["object_types"]:
                            variants_map[sequence]["object_types"].append(ot)
                except Exception as e:
                    logger.debug(f"Could not extract variants for {ot}: {e}")
                    continue
            
            # Sort by frequency and limit
            sorted_variants = sorted(
                variants_map.values(),
                key=lambda x: x["frequency"],
                reverse=True,
            )[:limit]
            
            logger.info(f"Object-centric variants extracted: {len(sorted_variants)}")
            return sorted_variants
        
        except Exception as e:
            logger.error(f"Error extracting object-centric variants: {e}")
            return []
    
    def get_performance_metrics(
        self, object_type: Optional[str] = None
    ) -> PerformanceMetricsDict:
        """
        Calculate performance metrics: times between consecutive activities.
        Uses PM4PY's ocel_flattening to get per-object traces, then calculates transition times.
        All times are in SECONDS (SI unit).

        Args:
            object_type: Filter by object type (optional).

        Returns:
            PerformanceMetricsDict with activity transition times in seconds.
        """
        logger.info(f"Calculating performance metrics (object_type={object_type})")
        
        try:
            import numpy as np
            
            ocel = self.ocel_data
            
            # Get object types to process
            if object_type:
                object_types = [object_type]
            else:
                object_types = pm4py.ocel_get_object_types(ocel)
            
            # Collect transition times across all object types
            transition_times: Dict[str, List[float]] = {}
            
            for ot in object_types:
                try:
                    # Flatten OCEL to traditional log for this object type
                    flat_log = pm4py.ocel_flattening(ocel, ot)
                    
                    # Group by case and calculate transition times
                    for case_id in flat_log['case:concept:name'].unique():
                        case_events = flat_log[flat_log['case:concept:name'] == case_id]
                        case_events = case_events.sort_values('time:timestamp')
                        
                        if len(case_events) < 2:
                            continue
                        
                        timestamps = case_events['time:timestamp'].tolist()
                        activities = case_events['concept:name'].tolist()
                        
                        for i in range(len(activities) - 1):
                            transition = f"{activities[i]} → {activities[i+1]}"
                            
                            t1 = timestamps[i]
                            t2 = timestamps[i+1]
                            
                            # Calculate time difference in seconds
                            if hasattr(t1, 'timestamp'):
                                delta_seconds = t2.timestamp() - t1.timestamp()
                            else:
                                delta_seconds = (t2 - t1).total_seconds()
                            
                            if transition not in transition_times:
                                transition_times[transition] = []
                            transition_times[transition].append(delta_seconds)
                except Exception as e:
                    logger.debug(f"Could not process {ot} for metrics: {e}")
                    continue
            
            # Calculate statistics
            metrics = {
                "time_unit": "seconds",
                "transitions": {},
                "total_transitions_analyzed": sum(len(v) for v in transition_times.values()),
            }
            
            for transition, times in transition_times.items():
                if times:
                    metrics["transitions"][transition] = {
                        "count": len(times),
                        "avg_seconds": round(float(np.mean(times)), 2),
                        "min_seconds": round(float(np.min(times)), 2),
                        "max_seconds": round(float(np.max(times)), 2),
                        "median_seconds": round(float(np.median(times)), 2),
                        "std_seconds": round(float(np.std(times)), 2),
                    }
            
            logger.info(f"Performance metrics calculated for {len(transition_times)} transitions")
            return metrics
        
        except ImportError:
            logger.error("NumPy required for performance metrics")
            return {"error": "NumPy not available", "time_unit": "seconds"}
        except Exception as e:
            logger.error(f"Error calculating performance metrics: {e}")
            return {"error": str(e), "time_unit": "seconds"}
    
    def detect_bottlenecks(
        self, object_type: Optional[str] = None, threshold_percentile: float = 90.0
    ) -> BottleneckResultDict:
        """
        Detect bottlenecks based on waiting times above threshold percentile.
        All times are in SECONDS (SI unit).

        Args:
            object_type: Filter by object type (optional).
            threshold_percentile: Percentile above which transitions are bottlenecks.

        Returns:
            BottleneckResultDict with identified bottlenecks and their metrics.
        """
        logger.info(f"Detecting bottlenecks (threshold={threshold_percentile}%)")
        
        # Get performance metrics first
        metrics = self.get_performance_metrics(object_type)
        
        if "error" in metrics:
            return metrics
        
        try:
            import numpy as np
            
            transitions = metrics.get("transitions", {})
            if not transitions:
                return {
                    "bottlenecks": [],
                    "threshold_percentile": threshold_percentile,
                    "time_unit": "seconds",
                }
            
            # Get all average times
            avg_times = [t["avg_seconds"] for t in transitions.values()]
            threshold_value = float(np.percentile(avg_times, threshold_percentile))
            
            # Find bottlenecks
            bottlenecks = []
            for transition, stats in transitions.items():
                if stats["avg_seconds"] >= threshold_value:
                    bottlenecks.append({
                        "transition": transition,
                        "avg_seconds": stats["avg_seconds"],
                        "max_seconds": stats["max_seconds"],
                        "count": stats["count"],
                        "severity": "high" if stats["avg_seconds"] > threshold_value * 1.5 else "medium",
                    })
            
            # Sort by average time descending
            bottlenecks.sort(key=lambda x: x["avg_seconds"], reverse=True)
            
            logger.info(f"Detected {len(bottlenecks)} bottlenecks")
            return {
                "bottlenecks": bottlenecks,
                "threshold_percentile": threshold_percentile,
                "threshold_seconds": round(threshold_value, 2),
                "time_unit": "seconds",
                "total_transitions": len(transitions),
            }
        
        except ImportError:
            return {"error": "NumPy not available", "time_unit": "seconds"}
        except Exception as e:
            logger.error(f"Error detecting bottlenecks: {e}")
            return {"error": str(e), "time_unit": "seconds"}
    
    def check_conformance(
        self, object_type: Optional[str] = None
    ) -> ConformanceResultDict:
        """
        Check conformance of log traces against discovered Petri net model.
        Uses PM4PY's ocel_flattening to get per-object traces for conformance checking.

        Args:
            object_type: Filter by object type (optional).

        Returns:
            ConformanceResultDict with fitness score and deviation details.
        """
        logger.info(f"Checking conformance (object_type={object_type})")
        
        try:
            ocel = self.ocel_data
            if object_type:
                ocel = pm4py.filter_ocel_object_types(ocel, [object_type])
            
            # Discover OC-PN for conformance
            oc_pn = pm4py.discover_oc_petri_net(ocel)
            petri_nets = oc_pn.get("petri_nets", {})
            
            # Get DFG edges for simple conformance check
            dfg_dict, _ = self.discover_dfg(object_type)
            edges = {(e["source"], e["target"]) for e in dfg_dict.get("edges", [])}
            
            # Get object types to check
            if object_type:
                object_types = [object_type]
            else:
                object_types = pm4py.ocel_get_object_types(ocel)[:3]  # Limit for performance
            
            complete_traces = 0
            total_traces = 0
            deviations = []
            
            for ot in object_types:
                try:
                    flat_log = pm4py.ocel_flattening(ocel, ot)
                    case_ids = list(flat_log['case:concept:name'].unique())[:100]  # Sample
                    
                    for case_id in case_ids:
                        case_events = flat_log[flat_log['case:concept:name'] == case_id]
                        case_events = case_events.sort_values('time:timestamp')
                        activities = case_events['concept:name'].tolist()
                        
                        total_traces += 1
                        is_conformant = True
                        
                        for i in range(len(activities) - 1):
                            if (activities[i], activities[i+1]) not in edges:
                                is_conformant = False
                                if len(deviations) < 50:
                                    deviations.append({
                                        "object_id": str(case_id),
                                        "deviation": f"Unexpected: {activities[i]} → {activities[i+1]}",
                                        "position": i,
                                    })
                                break
                        
                        if is_conformant:
                            complete_traces += 1
                except Exception as e:
                    logger.debug(f"Could not check conformance for {ot}: {e}")
                    continue
            
            fitness = complete_traces / total_traces if total_traces > 0 else 0.0
            
            logger.info(f"Conformance checked: fitness={fitness:.2%}")
            
            # Count total places and transitions
            total_places = sum(len(net.places) for net, _, _ in petri_nets.values())
            total_transitions = sum(len(net.transitions) for net, _, _ in petri_nets.values())
            
            return {
                "fitness_score": round(fitness, 4),
                "fitness_percentage": round(fitness * 100, 2),
                "sample_size": total_traces,
                "conformant_traces": complete_traces,
                "deviations": deviations[:20],
                "total_deviations": len(deviations),
                "model": {
                    "object_types": list(petri_nets.keys()),
                    "total_places": total_places,
                    "total_transitions": total_transitions,
                },
            }
        
        except Exception as e:
            logger.error(f"Error in conformance checking: {e}")
            return {"error": str(e)}
    
    def analyze_object_interactions(self) -> ObjectInteractionsResultDict:
        """
        Analyze co-occurrence patterns between object types in shared events.

        Returns:
            ObjectInteractionsResultDict with interaction matrix and patterns.
        """
        logger.info("Analyzing object interactions")
        
        try:
            # Build co-occurrence matrix
            objects_df = self.ocel_data.objects
            relations = self.ocel_data.relations if hasattr(self.ocel_data, "relations") else None
            
            # Get object types
            object_types = list(set(objects_df["ocel:type"].tolist()))
            
            # Initialize matrix
            co_occurrence: Dict[str, Dict[str, int]] = {
                ot1: {ot2: 0 for ot2 in object_types}
                for ot1 in object_types
            }
            
            # Count co-occurrences in events
            # relations already contains ocel:type, so we can use it directly
            if relations is not None and not relations.empty:
                # Group by event ID and get object types per event
                for eid in relations["ocel:eid"].unique():
                    event_relations = relations[relations["ocel:eid"] == eid]
                    types_in_event = event_relations["ocel:type"].tolist()
                    
                    # Count pairs (including self-pairs for same type)
                    for i, t1 in enumerate(types_in_event):
                        for t2 in types_in_event[i:]:
                            co_occurrence[t1][t2] += 1
                            if t1 != t2:
                                co_occurrence[t2][t1] += 1
            
            # Find strongest interactions
            interactions = []
            for t1 in object_types:
                for t2 in object_types:
                    if t1 <= t2 and co_occurrence[t1][t2] > 0:
                        interactions.append({
                            "type_1": t1,
                            "type_2": t2,
                            "co_occurrences": co_occurrence[t1][t2],
                        })
            
            interactions.sort(key=lambda x: x["co_occurrences"], reverse=True)
            
            logger.info(f"Found {len(interactions)} object type interactions")
            return {
                "object_types": object_types,
                "co_occurrence_matrix": co_occurrence,
                "top_interactions": interactions[:10],
                "total_pairs_analyzed": len(interactions),
            }
        
        except Exception as e:
            logger.error(f"Error analyzing object interactions: {e}")
            return {"error": str(e)}
    
    def get_available_resource_attributes(self) -> List[str]:
        """
        List available attributes that could represent resources/actors.

        Returns:
            List of attribute names that may contain resource information.
        """
        logger.info("Getting available resource attributes")
        
        try:
            attributes = []
            
            events_df = self.ocel_data.events
            
            # Check event columns for potential resource attributes
            resource_keywords = ["resource", "user", "actor", "agent", "org", "role", "worker", "employee"]
            
            for col in events_df.columns:
                col_lower = col.lower()
                # Skip OCEL reserved columns
                if col.startswith("ocel:"):
                    continue
                
                # Check if column name suggests resource
                if any(kw in col_lower for kw in resource_keywords):
                    attributes.append(col)
                # Also include any string columns that might be resources
                elif events_df[col].dtype == "object":
                    unique_ratio = events_df[col].nunique() / len(events_df)
                    # If low cardinality, might be resource
                    if 0.01 < unique_ratio < 0.3:
                        attributes.append(col)
            
            logger.info(f"Found {len(attributes)} potential resource attributes")
            return list(set(attributes))
        
        except Exception as e:
            logger.error(f"Error getting resource attributes: {e}")
            return []
    
    def discover_social_network(
        self, resource_attribute: str
    ) -> SocialNetworkResultDict:
        """
        Discover social/organizational network based on handovers between resources.
        Uses PM4PY's ocel_flattening to get per-object traces for handover detection.

        Args:
            resource_attribute: Attribute name containing resource/actor info.

        Returns:
            SocialNetworkResultDict with network nodes and edges.
        """
        logger.info(f"Discovering social network (attribute={resource_attribute})")
        
        try:
            events_df = self.ocel_data.events
            
            if resource_attribute not in events_df.columns:
                available = self.get_available_resource_attributes()
                return {
                    "error": f"Attribute '{resource_attribute}' not found",
                    "available_attributes": available,
                }
            
            # Build handover network using flattened logs
            handovers: Dict[str, Dict[str, int]] = {}
            resources = set()
            
            object_types = pm4py.ocel_get_object_types(self.ocel_data)
            
            for ot in object_types:
                try:
                    flat_log = pm4py.ocel_flattening(self.ocel_data, ot)
                    
                    # Check if resource attribute is in flattened log
                    if resource_attribute not in flat_log.columns:
                        continue
                    
                    for case_id in flat_log['case:concept:name'].unique():
                        case_events = flat_log[flat_log['case:concept:name'] == case_id]
                        case_events = case_events.sort_values('time:timestamp')
                        
                        if len(case_events) < 2:
                            continue
                        
                        resource_sequence = case_events[resource_attribute].tolist()
                        
                        for i in range(len(resource_sequence) - 1):
                            r1 = str(resource_sequence[i]) if resource_sequence[i] is not None else ""
                            r2 = str(resource_sequence[i+1]) if resource_sequence[i+1] is not None else ""
                            
                            if r1 and r2 and r1 != r2 and r1 != 'nan' and r2 != 'nan':
                                resources.add(r1)
                                resources.add(r2)
                                
                                if r1 not in handovers:
                                    handovers[r1] = {}
                                if r2 not in handovers[r1]:
                                    handovers[r1][r2] = 0
                                handovers[r1][r2] += 1
                except Exception as e:
                    logger.debug(f"Could not process {ot} for social network: {e}")
                    continue
            
            # Convert to edge list
            edges = []
            for source, targets in handovers.items():
                for target, weight in targets.items():
                    edges.append({
                        "source": source,
                        "target": target,
                        "weight": weight,
                    })
            
            edges.sort(key=lambda x: x["weight"], reverse=True)
            
            logger.info(f"Social network: {len(resources)} nodes, {len(edges)} edges")
            return {
                "nodes": list(resources),
                "edges": edges,
                "total_nodes": len(resources),
                "total_edges": len(edges),
                "resource_attribute": resource_attribute,
            }
        
        except Exception as e:
            logger.error(f"Error discovering social network: {e}")
            return {"error": str(e)}
    
    @staticmethod
    def invalidate_cache() -> None:
        """Invalidate the model cache. Call when OCEL data changes."""
        _model_cache.invalidate()
    
    @staticmethod
    def get_cache_stats() -> Dict[str, Any]:
        """Get cache statistics."""
        return _model_cache.stats()
