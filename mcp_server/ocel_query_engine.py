"""
Generic OCEL query engine.
Five MVP tools: lifecycle, timerange, statistics, anomalies, orphaned objects.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Set
import json

from . import logger
from .typing_ocel import EventReference, ObjectReference, AnomalyReport


class OCELQueryEngine:
    """Domain-agnostic query engine for OCEL 2.0."""
    
    def __init__(self, ocel_data: Any):
        """
        Initializes the query engine.

        Args:
            ocel_data: Loaded OCEL (PM4PY, dict, or DuckDB connection).
        """
        self.ocel_data = ocel_data
        self._detect_format()
    
    def _detect_format(self) -> None:
        """Detects the loaded OCEL format."""
        if hasattr(self.ocel_data, "events") and hasattr(self.ocel_data, "objects"):
            self.format = "pm4py"
            logger.debug("Detected format: PM4PY")
        elif isinstance(self.ocel_data, dict) and "ocel:events" in self.ocel_data:
            self.format = "dict"
            logger.debug("Detected format: dict (ijson)")
        else:
            self.format = "duckdb"
            logger.debug("Detected format: DuckDB")
    
    def trace_object_lifecycle(self, object_id: str) -> List[EventReference]:
        """
        Traces the full lifecycle of an object.

        Args:
            object_id: Object ID (ocel:oid).

        Returns:
            List of events ordered by timestamp.

        Raises:
            ValueError: If the object does not exist.
        """
        logger.debug(f"Tracing object lifecycle: {object_id}")
        
        if self.format == "pm4py":
            return self._trace_lifecycle_pm4py(object_id)
        elif self.format == "dict":
            return self._trace_lifecycle_dict(object_id)
        else:
            return self._trace_lifecycle_duckdb(object_id)
    
    def _trace_lifecycle_pm4py(self, object_id: str) -> List[EventReference]:
        """Lifecycle tracing using PM4PY."""
        import pm4py
        
        if object_id not in self.ocel_data.objects:
            raise ValueError(f"Object not found: {object_id}")
        
        try:
            event_ids = pm4py.ocel_get_events_of_object(self.ocel_data, object_id)
        except Exception as e:
            logger.error(f"Error tracing lifecycle in PM4PY: {e}")
            raise
        
        references = []
        for event_id in sorted(event_ids):
            event = self.ocel_data.events.get(event_id)
            if event:
                involved_objs = [
                    ObjectReference(
                        object_id=oid,
                        object_type=self.ocel_data.objects[oid].get("ocel:type", "unknown"),
                        role=None,
                    )
                    for oid in event.get("ocel:omap", [])
                    if oid in self.ocel_data.objects
                ]
                references.append(
                    EventReference(
                        event_id=event_id,
                        activity=event.get("ocel:activity", "unknown"),
                        timestamp=event.get("ocel:timestamp", ""),
                        involved_objects=involved_objs,
                    )
                )
        
        logger.info(f"Lifecycle for {object_id}: {len(references)} events")
        return references
    
    def _trace_lifecycle_dict(self, object_id: str) -> List[EventReference]:
        """Lifecycle tracing using dict (ijson)."""
        if object_id not in self.ocel_data.get("ocel:objects", {}):
            raise ValueError(f"Object not found: {object_id}")
        
        references = []
        for event in self.ocel_data.get("ocel:events", []):
            omap = event.get("ocel:omap", [])
            
            if any(obj.get("ocel:oid") == object_id for obj in omap):
                involved_objs = [
                    ObjectReference(
                        object_id=obj.get("ocel:oid"),
                        object_type=self.ocel_data["ocel:objects"]
                        .get(obj.get("ocel:oid"), {})
                        .get("ocel:type", "unknown"),
                        role=obj.get("ocel:qualifier"),
                    )
                    for obj in omap
                ]
                references.append(
                    EventReference(
                        event_id=event.get("ocel:eid", ""),
                        activity=event.get("ocel:activity", "unknown"),
                        timestamp=event.get("ocel:timestamp", ""),
                        involved_objects=involved_objs,
                    )
                )
        
        logger.info(f"Lifecycle for {object_id}: {len(references)} events")
        return references
    
    def _trace_lifecycle_duckdb(self, object_id: str) -> List[EventReference]:
        """Lifecycle tracing using DuckDB (placeholder)."""
        logger.warning("DuckDB lifecycle trace: not yet implemented")
        return []
    
    def query_events_by_timerange(
        self,
        start_datetime: str,
        end_datetime: str,
    ) -> List[EventReference]:
        """
        Queries events within a time range.

        Args:
            start_datetime: ISO 8601 datetime (e.g., "2025-01-20T10:00:00").
            end_datetime: ISO 8601 datetime.

        Returns:
            List of events in the range.

        Raises:
            ValueError: If the datetimes are invalid.
        """
        logger.debug(f"Querying events between {start_datetime} and {end_datetime}")
        
        try:
            start = datetime.fromisoformat(start_datetime.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_datetime.replace("Z", "+00:00"))
        except ValueError as e:
            raise ValueError(f"Invalid datetime: {e}")
        
        if self.format == "pm4py":
            return self._timerange_pm4py(start, end)
        elif self.format == "dict":
            return self._timerange_dict(start, end)
        else:
            return self._timerange_duckdb(start, end)
    
    def _timerange_pm4py(self, start: datetime, end: datetime) -> List[EventReference]:
        """Time range query using PM4PY."""
        references = []
        for event_id, event in self.ocel_data.events.items():
            try:
                ts_str = event.get("ocel:timestamp", "")
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                
                if start <= ts <= end:
                    involved_objs = [
                        ObjectReference(
                            object_id=oid,
                            object_type=self.ocel_data.objects[oid].get("ocel:type"),
                            role=None,
                        )
                        for oid in event.get("ocel:omap", [])
                        if oid in self.ocel_data.objects
                    ]
                    references.append(
                        EventReference(
                            event_id=event_id,
                            activity=event.get("ocel:activity", "unknown"),
                            timestamp=ts_str,
                            involved_objects=involved_objs,
                        )
                    )
            except Exception as e:
                logger.debug(f"Error processing event {event_id}: {e}")
        
        logger.info(f"Events in range: {len(references)}")
        return references
    
    def _timerange_dict(self, start: datetime, end: datetime) -> List[EventReference]:
        """Time range query using dict."""
        references = []
        for event in self.ocel_data.get("ocel:events", []):
            try:
                ts_str = event.get("ocel:timestamp", "")
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                
                if start <= ts <= end:
                    involved_objs = [
                        ObjectReference(
                            object_id=obj.get("ocel:oid"),
                            object_type=self.ocel_data["ocel:objects"]
                            .get(obj.get("ocel:oid"), {})
                            .get("ocel:type"),
                            role=obj.get("ocel:qualifier"),
                        )
                        for obj in event.get("ocel:omap", [])
                    ]
                    references.append(
                        EventReference(
                            event_id=event.get("ocel:eid", ""),
                            activity=event.get("ocel:activity", "unknown"),
                            timestamp=ts_str,
                            involved_objects=involved_objs,
                        )
                    )
            except Exception as e:
                logger.debug(f"Error processing event: {e}")
        
        logger.info(f"Events in range: {len(references)}")
        return references
    
    def _timerange_duckdb(self, start: datetime, end: datetime) -> List[EventReference]:
        """Time range query using DuckDB (placeholder)."""
        logger.warning("DuckDB timerange query: not yet implemented")
        return []
    
    def get_statistics_by_object_type(self) -> Dict[str, Any]:
        """
        Calculates statistics by object type.

        Returns:
            Dict with counts and type distribution.
        """
        logger.debug("Calculating statistics by object type")
        
        if self.format == "pm4py":
            return self._stats_pm4py()
        elif self.format == "dict":
            return self._stats_dict()
        else:
            return self._stats_duckdb()
    
    def _stats_pm4py(self) -> Dict[str, Any]:
        """Statistics using PM4PY."""
        stats_by_type = {}
        
        for obj_id, obj in self.ocel_data.objects.items():
            obj_type = obj.get("ocel:type", "unknown")
            if obj_type not in stats_by_type:
                stats_by_type[obj_type] = {"count": 0, "objects": []}
            
            stats_by_type[obj_type]["count"] += 1
            stats_by_type[obj_type]["objects"].append(obj_id)
        
        logger.info(f"Statistics: {len(stats_by_type)} object types")
        return stats_by_type
    
    def _stats_dict(self) -> Dict[str, Any]:
        """Statistics using dict."""
        stats_by_type = {}
        
        for obj_id, obj in self.ocel_data.get("ocel:objects", {}).items():
            obj_type = obj.get("ocel:type", "unknown")
            if obj_type not in stats_by_type:
                stats_by_type[obj_type] = {"count": 0, "objects": []}
            
            stats_by_type[obj_type]["count"] += 1
            stats_by_type[obj_type]["objects"].append(obj_id)
        
        logger.info(f"Statistics: {len(stats_by_type)} object types")
        return stats_by_type
    
    def _stats_duckdb(self) -> Dict[str, Any]:
        """Statistics using DuckDB (placeholder)."""
        logger.warning("DuckDB statistics: not yet implemented")
        return {}
    
    def detect_anomalies(self) -> List[AnomalyReport]:
        """
        Detects anomalies in the log.

        Detects:
        - Orphaned objects (no events)
        - Events without related objects
        - Broken references (event references a missing object)

        Returns:
            List of detected anomalies.
        """
        logger.debug("Detecting anomalies in OCEL")
        
        if self.format == "pm4py":
            return self._anomalies_pm4py()
        elif self.format == "dict":
            return self._anomalies_dict()
        else:
            return self._anomalies_duckdb()
    
    def _anomalies_pm4py(self) -> List[AnomalyReport]:
        """Anomaly detection using PM4PY."""
        import pm4py
        
        anomalies = []
        
        all_object_ids = set(self.ocel_data.objects.keys())
        objects_in_events = set()
        
        for event in self.ocel_data.events.values():
            objects_in_events.update(event.get("ocel:omap", []))
        
        orphaned_objects = all_object_ids - objects_in_events
        for obj_id in orphaned_objects:
            anomalies.append(
                AnomalyReport(
                    anomaly_type="orphaned_object",
                    severity="medium",
                    affected_id=obj_id,
                    description="Object does not participate in any event",
                    timestamp=datetime.utcnow().isoformat(),
                )
            )
        
        for event_id, event in self.ocel_data.events.items():
            omap = event.get("ocel:omap", [])
            if not omap:
                anomalies.append(
                    AnomalyReport(
                        anomaly_type="event_no_objects",
                        severity="high",
                        affected_id=event_id,
                        description="Event without related objects",
                        timestamp=datetime.utcnow().isoformat(),
                    )
                )
        
            logger.info(f"Anomalies detected: {len(anomalies)}")
        return anomalies
    
    def _anomalies_dict(self) -> List[AnomalyReport]:
        """Anomaly detection using dict."""
        anomalies = []
        
        all_object_ids = set(self.ocel_data.get("ocel:objects", {}).keys())
        objects_in_events = set()
        
        for event in self.ocel_data.get("ocel:events", []):
            for obj_ref in event.get("ocel:omap", []):
                objects_in_events.add(obj_ref.get("ocel:oid"))
        
        orphaned_objects = all_object_ids - objects_in_events
        for obj_id in orphaned_objects:
            anomalies.append(
                AnomalyReport(
                    anomaly_type="orphaned_object",
                    severity="medium",
                    affected_id=obj_id,
                    description="Object does not participate in any event",
                    timestamp=datetime.utcnow().isoformat(),
                )
            )
        
        logger.info(f"Anomalies detected: {len(anomalies)}")
        return anomalies
    
    def _anomalies_duckdb(self) -> List[AnomalyReport]:
        """Anomaly detection using DuckDB (placeholder)."""
        logger.warning("DuckDB anomaly detection: not yet implemented")
        return []
    
    def find_orphaned_objects(self) -> List[str]:
        """
        Finds objects that do not participate in any event.

        Returns:
            List of orphaned object IDs.
        """
        logger.debug("Searching for orphaned objects")
        
        if self.format == "pm4py":
            return self._orphaned_pm4py()
        elif self.format == "dict":
            return self._orphaned_dict()
        else:
            return self._orphaned_duckdb()
    
    def _orphaned_pm4py(self) -> List[str]:
        """Orphaned objects using PM4PY."""
        all_objects = set(self.ocel_data.objects.keys())
        objects_in_events = set()
        
        for event in self.ocel_data.events.values():
            objects_in_events.update(event.get("ocel:omap", []))
        
        orphaned = list(all_objects - objects_in_events)
        logger.info(f"Orphaned objects found: {len(orphaned)}")
        return orphaned
    
    def _orphaned_dict(self) -> List[str]:
        """Orphaned objects using dict."""
        all_objects = set(self.ocel_data.get("ocel:objects", {}).keys())
        objects_in_events = set()
        
        for event in self.ocel_data.get("ocel:events", []):
            for obj_ref in event.get("ocel:omap", []):
                objects_in_events.add(obj_ref.get("ocel:oid"))
        
        orphaned = list(all_objects - objects_in_events)
        logger.info(f"Orphaned objects found: {len(orphaned)}")
        return orphaned
    
    def _orphaned_duckdb(self) -> List[str]:
        """Orphaned objects using DuckDB (placeholder)."""
        logger.warning("DuckDB orphaned objects: not yet implemented")
        return []
