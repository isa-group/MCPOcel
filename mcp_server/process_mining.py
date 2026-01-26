"""
PM4PY wrapper for domain-agnostic process mining.
Exposes: DFG discovery, Petri net discovery, variants, and statistics.
"""

from typing import Any, Dict, List, Optional, Tuple
import json

from . import logger

try:
    import pm4py
except ImportError:
    logger.error("PM4PY not installed. Install with: pip install pm4py")
    pm4py = None


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
            self.format = "duckdb"
            logger.debug("Detected format: DuckDB")
    
    def discover_dfg(
        self, object_type: Optional[str] = None
    ) -> Tuple[Dict, Dict]:
        """
        Discovers an object-centric Directly Follows Graph (DFG).

        Args:
            object_type: Object type filter (None = all).

        Returns:
            (dfg_dict, freq_net_dict): Tuple with DFG and frequencies.
        """
        logger.info(f"Discovering OC-DFG (object_type={object_type})")
        
        if self.format == "pm4py":
            return self._discover_dfg_pm4py(object_type)
        elif self.format == "dict":
            return self._discover_dfg_dict(object_type)
        else:
            logger.warning("DFG discovery with DuckDB: not implemented")
            return {}, {}
    
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
        self, object_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Discovers an Object-Centric Petri Net (OC-PN).

        Args:
            object_type: Object type filter (None = all).

        Returns:
            Dict with places, transitions, and start/end data.
        """
        logger.info(f"Discovering OC-PN (object_type={object_type})")
        
        if self.format == "pm4py":
            return self._discover_petri_net_pm4py(object_type)
        elif self.format == "dict":
            return self._discover_petri_net_dict(object_type)
        else:
            logger.warning("Petri net discovery with DuckDB: not implemented")
            return {}
    
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
        elif self.format == "dict":
            return self._variants_dict(object_type, limit)
        else:
            logger.warning("Variant extraction with DuckDB: not implemented")
            return []
    
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
        elif self.format == "dict":
            return self._stats_dict()
        else:
            return self._stats_duckdb()
    
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
    
    def _stats_duckdb(self) -> Dict[str, Any]:
        """Statistics using DuckDB (placeholder)."""
        logger.warning("DuckDB statistics: not implemented")
        return {}
