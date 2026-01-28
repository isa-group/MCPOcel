"""
PM4PY wrapper for domain-agnostic process mining.
Exposes: DFG discovery, Petri net discovery, variants, and statistics.
"""

from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import hashlib
import json

from shared.logger.logging_config import get_logger

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
    
    def __init__(self, ocel_data: Any):
        """
        Initializes the process mining engine.

        Args:
            ocel_data: Loaded OCEL (PM4PY, dict, or DuckDB).
        """
        if pm4py is None:
            raise ImportError("PM4PY is not available")
        
        self.ocel_data = ocel_data
        self._detect_format()
    
    def _detect_format(self) -> None:
        """Detects the OCEL format."""
        if hasattr(self.ocel_data, "events") and hasattr(self.ocel_data, "objects"):
            self.format = "pm4py"
            logger.debug("Detected format: PM4PY")
        elif isinstance(self.ocel_data, dict) and "ocel:events" in self.ocel_data:
            self.format = "dict"
            logger.debug("Detected format: dict (ijson)")
        else:
            self.format = "unknown"
            logger.warning("Unknown OCEL format - some operations may not work")
    
    def discover_dfg(
        self, object_type: Optional[str] = None, use_cache: bool = True
    ) -> Tuple[Dict, Dict]:
        """
        Discovers an object-centric Directly Follows Graph (DFG).

        Args:
            object_type: Object type filter (None = all).
            use_cache: Whether to use cached results (default: True).

        Returns:
            (dfg_dict, freq_net_dict): Tuple with DFG and frequencies.
        """
        # Check cache first
        if use_cache:
            cached = _model_cache.get("dfg", object_type)
            if cached is not None:
                return cached
        
        logger.info(f"Discovering OC-DFG (object_type={object_type})")
        
        if self.format == "pm4py":
            result = self._discover_dfg_pm4py(object_type)
        else:
            result = self._discover_dfg_dict(object_type)
        
        # Store in cache
        if use_cache and result[0]:
            _model_cache.set("dfg", object_type, result)
        
        return result
    
    def _discover_dfg_pm4py(
        self, object_type: Optional[str] = None
    ) -> Tuple[Dict, Dict]:
        """Discovers a DFG using PM4PY."""
        try:
            if object_type:
                filtered = pm4py.ocel_filter_object_types(
                    self.ocel_data, [object_type]
                )
                dfg = pm4py.discover_ocel_dfg(filtered)
            else:
                dfg = pm4py.discover_ocel_dfg(self.ocel_data)
            
            dfg_dict = {
                "edges": [
                    {
                        "source": str(edge[0]),
                        "target": str(edge[1]),
                        "frequency": int(freq),
                    }
                    for edge, freq in dfg[0].items()
                ],
                "start_activities": [
                    {"activity": str(act), "frequency": int(freq)}
                    for act, freq in (dfg[1] if len(dfg) > 1 else {}).items()
                ],
            }
            
            logger.info(f"DFG discovered: {len(dfg_dict['edges'])} edges")
            return dfg_dict, {}
        
        except Exception as e:
            logger.error(f"Error discovering DFG: {e}")
            raise
    
    def _discover_dfg_dict(
        self, object_type: Optional[str] = None
    ) -> Tuple[Dict, Dict]:
        """Discovers a DFG using dict input (converted to PM4PY)."""
        logger.warning("DFG discovery with dict input: converting to PM4PY")
        try:
            temp_path = "/tmp/temp_ocel.json"
            with open(temp_path, "w") as f:
                json.dump(self.ocel_data, f)
            
            ocel = pm4py.read_ocel(temp_path)
            result = self._discover_dfg_pm4py_with_ocel(ocel, object_type)
            return result
        except Exception as e:
            logger.error(f"Error in DFG dict workflow: {e}")
            return {}, {}
    
    def _discover_dfg_pm4py_with_ocel(
        self, ocel: Any, object_type: Optional[str] = None
    ) -> Tuple[Dict, Dict]:
        """Helper for DFG discovery with PM4PY OCEL objects."""
        try:
            if object_type:
                filtered = pm4py.ocel_filter_object_types(ocel, [object_type])
                dfg = pm4py.discover_ocel_dfg(filtered)
            else:
                dfg = pm4py.discover_ocel_dfg(ocel)
            
            dfg_dict = {
                "edges": [
                    {
                        "source": str(edge[0]),
                        "target": str(edge[1]),
                        "frequency": int(freq),
                    }
                    for edge, freq in dfg[0].items()
                ],
            }
            
            return dfg_dict, {}
        except Exception as e:
            logger.error(f"Error in PM4PY DFG discovery: {e}")
            return {}, {}
    
    def discover_petri_net(
        self, object_type: Optional[str] = None, use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Discovers an Object-Centric Petri Net (OC-PN).

        Args:
            object_type: Object type filter (None = all).
            use_cache: Whether to use cached results (default: True).

        Returns:
            Dict with places, transitions, and start/end data.
        """
        # Check cache first
        if use_cache:
            cached = _model_cache.get("petri_net", object_type)
            if cached is not None:
                return cached
        
        logger.info(f"Discovering OC-PN (object_type={object_type})")
        
        if self.format == "pm4py":
            result = self._discover_petri_net_pm4py(object_type)
        else:
            result = self._discover_petri_net_dict(object_type)
        
        # Store in cache
        if use_cache and result:
            _model_cache.set("petri_net", object_type, result)
        
        return result
    
    def _discover_petri_net_pm4py(
        self, object_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Discovers a Petri net using PM4PY."""
        try:
            if object_type:
                filtered = pm4py.ocel_filter_object_types(
                    self.ocel_data, [object_type]
                )
                petri_net, im, fm = pm4py.discover_ocel_petri_net(filtered)
            else:
                petri_net, im, fm = pm4py.discover_ocel_petri_net(self.ocel_data)
            
            pn_dict = {
                "places": len(petri_net.places),
                "transitions": len(petri_net.transitions),
                "arcs": len(petri_net.arcs),
                "initial_marking": str(im),
                "final_marking": str(fm),
            }
            
            logger.info(f"Petri net discovered: {pn_dict['places']} places, "
                       f"{pn_dict['transitions']} transitions")
            return pn_dict
        
        except Exception as e:
            logger.error(f"Error discovering Petri net: {e}")
            raise
    
    def _discover_petri_net_dict(
        self, object_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Discovers a Petri net using dict input (converted to PM4PY)."""
        logger.warning("Petri net discovery with dict input: converting to PM4PY")
        try:
            temp_path = "/tmp/temp_ocel_pn.json"
            with open(temp_path, "w") as f:
                json.dump(self.ocel_data, f)
            
            ocel = pm4py.read_ocel(temp_path)
            return self._discover_petri_net_pm4py_with_ocel(ocel, object_type)
        except Exception as e:
            logger.error(f"Error in dict-based Petri net discovery: {e}")
            return {}
    
    def _discover_petri_net_pm4py_with_ocel(
        self, ocel: Any, object_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Helper for Petri net discovery with PM4PY OCEL objects."""
        try:
            if object_type:
                filtered = pm4py.ocel_filter_object_types(ocel, [object_type])
                petri_net, im, fm = pm4py.discover_ocel_petri_net(filtered)
            else:
                petri_net, im, fm = pm4py.discover_ocel_petri_net(ocel)
            
            pn_dict = {
                "places": len(petri_net.places),
                "transitions": len(petri_net.transitions),
                "arcs": len(petri_net.arcs),
                "initial_marking": str(im),
                "final_marking": str(fm),
            }
            
            return pn_dict
        except Exception as e:
            logger.error(f"Error in PM4PY Petri net discovery: {e}")
            return {}
    
    def extract_process_variants(
        self, object_type: Optional[str] = None, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Extracts process variants (activity sequences).

        Args:
            object_type: Object type filter.
            limit: Maximum variants to return (top-N) to keep responses manageable; defaults to 10.

        Returns:
            List of variants ordered by frequency.
        """
        logger.info(f"Extracting process variants (limit={limit})")
        
        if self.format == "pm4py":
            return self._variants_pm4py(object_type, limit)
        else:
            return self._variants_dict(object_type, limit)
    
    def _variants_pm4py(
        self, object_type: Optional[str] = None, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Extracts variants using PM4PY."""
        # Default to top-10 to align with the public API and avoid massive outputs.
        variants = {}
        
        for event_id, event in self.ocel_data.events.items():
            activity = event.get("ocel:activity", "unknown")
            
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
    
    def _variants_dict(
        self, object_type: Optional[str] = None, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Extracts variants using dict input."""
        # Default to top-10 to align with the public API and avoid massive outputs.
        variants = {}
        
        for event in self.ocel_data.get("ocel:events", []):
            activity = event.get("ocel:activity", "unknown")
            
            if activity not in variants:
                variants[activity] = {
                    "activity_sequence": [activity],
                    "frequency": 0,
                    "sample_events": [],
                }
            
            variants[activity]["frequency"] += 1
            # Limit samples to 3 IDs to illustrate without inflating the payload.
            if len(variants[activity]["sample_events"]) < 3:
                variants[activity]["sample_events"].append(event.get("ocel:eid"))
        
        sorted_variants = sorted(
            variants.values(),
            key=lambda x: x["frequency"],
            reverse=True,
        )[:limit]
        
        logger.info(f"Variants extracted: {len(sorted_variants)}")
        return sorted_variants
    
    def get_ocel_statistics(self) -> Dict[str, Any]:
        """
        Retrieves general OCEL statistics.

        Returns:
            Dict with totals for events, objects, types, and distributions.
        """
        logger.debug("Fetching OCEL statistics")
        
        if self.format == "pm4py":
            return self._stats_pm4py()
        else:
            return self._stats_dict()
    
    def _stats_pm4py(self) -> Dict[str, Any]:
        """Statistics using PM4PY."""
        try:
            stats = pm4py.ocel_statistics.get_ocpn_stats(self.ocel_data)
            logger.info("OCEL statistics obtained")
            return {
                "total_events": len(self.ocel_data.events),
                "total_objects": len(self.ocel_data.objects),
                "object_types": len(set(
                    obj.get("ocel:type") for obj in self.ocel_data.objects.values()
                )),
                "event_types": len(set(
                    event.get("ocel:activity") for event in self.ocel_data.events.values()
                )),
            }
        except Exception as e:
            logger.error(f"Error obtaining PM4PY statistics: {e}")
            return {}
    
    def _stats_dict(self) -> Dict[str, Any]:
        """Statistics using dict."""
        event_types = set(
            event.get("ocel:activity") for event in self.ocel_data.get("ocel:events", [])
        )
        object_types = set(
            obj.get("ocel:type") for obj in self.ocel_data.get("ocel:objects", {}).values()
        )
        
        logger.info("OCEL statistics obtained (dict)")
        return {
            "total_events": len(self.ocel_data.get("ocel:events", [])),
            "total_objects": len(self.ocel_data.get("ocel:objects", {})),
            "object_types": len(object_types),
            "event_types": len(event_types),
        }
    
    # ========================================================================
    # NEW METHODS: Object-Centric Variants, Performance, Conformance
    # ========================================================================
    
    def extract_object_centric_variants(
        self, object_type: Optional[str] = None, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Extract true object-centric process variants.
        Groups complete activity sequences per object, then aggregates by unique sequence.

        Args:
            object_type: Filter by object type (optional).
            limit: Maximum variants to return.

        Returns:
            List of variants with sequence, frequency, and sample objects.
        """
        logger.info(f"Extracting object-centric variants (object_type={object_type}, limit={limit})")
        
        if self.format != "pm4py":
            logger.warning("Object-centric variants require PM4PY format")
            return self.extract_process_variants(object_type, limit)
        
        try:
            ocel = self.ocel_data
            if object_type:
                ocel = pm4py.ocel_filter_object_types(ocel, [object_type])
            
            # Get all objects
            objects_df = ocel.objects
            variants_map: Dict[str, Dict] = {}
            
            for oid in objects_df.index:
                try:
                    # Get events for this object
                    object_events = pm4py.ocel_get_object_events(ocel, oid)
                    if object_events.empty:
                        continue
                    
                    # Sort by timestamp and extract activity sequence
                    sorted_events = object_events.sort_values("ocel:timestamp")
                    sequence = tuple(sorted_events["ocel:activity"].tolist())
                    sequence_key = " → ".join(sequence)
                    
                    if sequence_key not in variants_map:
                        variants_map[sequence_key] = {
                            "activity_sequence": list(sequence),
                            "frequency": 0,
                            "sample_objects": [],
                        }
                    
                    variants_map[sequence_key]["frequency"] += 1
                    if len(variants_map[sequence_key]["sample_objects"]) < 3:
                        variants_map[sequence_key]["sample_objects"].append(str(oid))
                
                except Exception:
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
    ) -> Dict[str, Any]:
        """
        Calculate performance metrics: times between consecutive activities.
        All times are in SECONDS (SI unit).

        Args:
            object_type: Filter by object type (optional).

        Returns:
            Dict with activity transition times (avg, min, max, median) in seconds.
        """
        logger.info(f"Calculating performance metrics (object_type={object_type})")
        
        if self.format != "pm4py":
            logger.warning("Performance metrics require PM4PY format")
            return {"error": "PM4PY format required", "time_unit": "seconds"}
        
        try:
            import numpy as np
            
            ocel = self.ocel_data
            if object_type:
                ocel = pm4py.ocel_filter_object_types(ocel, [object_type])
            
            # Collect transition times
            transition_times: Dict[str, List[float]] = {}
            objects_df = ocel.objects
            
            for oid in objects_df.index:
                try:
                    object_events = pm4py.ocel_get_object_events(ocel, oid)
                    if len(object_events) < 2:
                        continue
                    
                    sorted_events = object_events.sort_values("ocel:timestamp")
                    timestamps = sorted_events["ocel:timestamp"].tolist()
                    activities = sorted_events["ocel:activity"].tolist()
                    
                    for i in range(len(activities) - 1):
                        transition = f"{activities[i]} → {activities[i+1]}"
                        
                        # Calculate time difference in seconds
                        t1 = timestamps[i]
                        t2 = timestamps[i+1]
                        
                        # Handle different timestamp formats
                        if hasattr(t1, 'timestamp'):
                            delta_seconds = (t2.timestamp() - t1.timestamp())
                        else:
                            delta_seconds = (t2 - t1).total_seconds()
                        
                        if transition not in transition_times:
                            transition_times[transition] = []
                        transition_times[transition].append(delta_seconds)
                
                except Exception:
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
    ) -> Dict[str, Any]:
        """
        Detect bottlenecks based on waiting times above threshold percentile.
        All times are in SECONDS (SI unit).

        Args:
            object_type: Filter by object type (optional).
            threshold_percentile: Percentile above which transitions are bottlenecks.

        Returns:
            Dict with identified bottlenecks and their metrics.
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
    ) -> Dict[str, Any]:
        """
        Check conformance of log traces against discovered Petri net model.

        Args:
            object_type: Filter by object type (optional).

        Returns:
            Dict with fitness score and deviation details.
        """
        logger.info(f"Checking conformance (object_type={object_type})")
        
        if self.format != "pm4py":
            return {"error": "PM4PY format required for conformance checking"}
        
        try:
            ocel = self.ocel_data
            if object_type:
                ocel = pm4py.ocel_filter_object_types(ocel, [object_type])
            
            # Discover Petri net for conformance
            petri_net, im, fm = pm4py.discover_ocel_petri_net(ocel)
            
            # Basic fitness calculation based on replay
            # Note: Full token-based replay for OCEL is complex; we use simplified metrics
            total_events = len(ocel.events)
            total_objects = len(ocel.objects)
            
            # Count objects with complete traces (start to end activities)
            complete_traces = 0
            deviations = []
            
            objects_df = ocel.objects
            for oid in list(objects_df.index)[:100]:  # Sample for performance
                try:
                    object_events = pm4py.ocel_get_object_events(ocel, oid)
                    if not object_events.empty:
                        activities = object_events.sort_values("ocel:timestamp")["ocel:activity"].tolist()
                        
                        # Simple check: does the sequence follow DFG edges?
                        dfg_dict, _ = self.discover_dfg(object_type)
                        edges = {(e["source"], e["target"]) for e in dfg_dict.get("edges", [])}
                        
                        is_conformant = True
                        for i in range(len(activities) - 1):
                            if (activities[i], activities[i+1]) not in edges:
                                is_conformant = False
                                deviations.append({
                                    "object_id": str(oid),
                                    "deviation": f"Unexpected: {activities[i]} → {activities[i+1]}",
                                    "position": i,
                                })
                                break
                        
                        if is_conformant:
                            complete_traces += 1
                
                except Exception:
                    continue
            
            sample_size = min(100, total_objects)
            fitness = complete_traces / sample_size if sample_size > 0 else 0.0
            
            logger.info(f"Conformance checked: fitness={fitness:.2%}")
            return {
                "fitness_score": round(fitness, 4),
                "fitness_percentage": round(fitness * 100, 2),
                "sample_size": sample_size,
                "conformant_traces": complete_traces,
                "deviations": deviations[:20],  # Limit for response size
                "total_deviations": len(deviations),
                "model": {
                    "places": len(petri_net.places),
                    "transitions": len(petri_net.transitions),
                },
            }
        
        except Exception as e:
            logger.error(f"Error in conformance checking: {e}")
            return {"error": str(e)}
    
    def analyze_object_interactions(self) -> Dict[str, Any]:
        """
        Analyze co-occurrence patterns between object types in shared events.

        Returns:
            Dict with interaction matrix and patterns.
        """
        logger.info("Analyzing object interactions")
        
        if self.format != "pm4py":
            return {"error": "PM4PY format required"}
        
        try:
            # Build co-occurrence matrix
            events_df = self.ocel_data.events
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
            if relations is not None and not relations.empty:
                for eid in events_df.index:
                    event_objects = relations[relations["ocel:eid"] == eid]["ocel:oid"].tolist()
                    types_in_event = []
                    
                    for oid in event_objects:
                        if oid in objects_df.index:
                            obj_type = objects_df.loc[oid, "ocel:type"]
                            types_in_event.append(obj_type)
                    
                    # Count pairs
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
            
            if self.format == "pm4py":
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
            else:
                # Dict format: check event attributes
                sample_event = self.ocel_data.get("ocel:events", [{}])[0]
                for key in sample_event.keys():
                    if not key.startswith("ocel:"):
                        attributes.append(key)
            
            logger.info(f"Found {len(attributes)} potential resource attributes")
            return list(set(attributes))
        
        except Exception as e:
            logger.error(f"Error getting resource attributes: {e}")
            return []
    
    def discover_social_network(
        self, resource_attribute: str
    ) -> Dict[str, Any]:
        """
        Discover social/organizational network based on handovers between resources.

        Args:
            resource_attribute: Attribute name containing resource/actor info.

        Returns:
            Dict with network nodes (resources) and edges (handovers).
        """
        logger.info(f"Discovering social network (attribute={resource_attribute})")
        
        if self.format != "pm4py":
            return {"error": "PM4PY format required"}
        
        try:
            events_df = self.ocel_data.events
            objects_df = self.ocel_data.objects
            
            if resource_attribute not in events_df.columns:
                available = self.get_available_resource_attributes()
                return {
                    "error": f"Attribute '{resource_attribute}' not found",
                    "available_attributes": available,
                }
            
            # Build handover network
            handovers: Dict[str, Dict[str, int]] = {}
            resources = set()
            
            for oid in objects_df.index:
                try:
                    object_events = pm4py.ocel_get_object_events(self.ocel_data, oid)
                    if len(object_events) < 2:
                        continue
                    
                    sorted_events = object_events.sort_values("ocel:timestamp")
                    resource_sequence = sorted_events[resource_attribute].tolist()
                    
                    for i in range(len(resource_sequence) - 1):
                        r1 = str(resource_sequence[i])
                        r2 = str(resource_sequence[i+1])
                        
                        if r1 and r2 and r1 != r2:  # Skip same resource or empty
                            resources.add(r1)
                            resources.add(r2)
                            
                            if r1 not in handovers:
                                handovers[r1] = {}
                            if r2 not in handovers[r1]:
                                handovers[r1][r2] = 0
                            handovers[r1][r2] += 1
                
                except Exception:
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
