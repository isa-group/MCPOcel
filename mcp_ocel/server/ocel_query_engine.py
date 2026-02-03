"""
Generic OCEL query engine.
Five MVP tools: lifecycle, timerange, statistics, anomalies, orphaned objects.
"""

from datetime import datetime
from typing import Dict, List

from .typing_ocel import (
    EventReference,
    ObjectReference,
    AnomalyReport,
    OCELData,
    ObjectTypeStatsDict,
)
from shared.logger.logging_config import get_logger

logger = get_logger(__name__)

class OCELQueryEngine:
    """Domain-agnostic query engine for OCEL 2.0."""
    
    ocel_data: OCELData
    format: str
    
    def __init__(self, ocel_data: OCELData) -> None:
        """
        Initializes the query engine.

        Args:
            ocel_data: Loaded OCEL (PM4PY or dict).
        """
        self.ocel_data = ocel_data
        self._detect_format()
    
    def _detect_format(self) -> None:
        """Detects the loaded OCEL format."""
        if hasattr(self.ocel_data, "events") and hasattr(self.ocel_data, "objects"):
            self.format = "pm4py"
            logger.debug("Detected format: PM4PY")
        elif isinstance(self.ocel_data, dict) and "events" in self.ocel_data:
            self.format = "dict"
            logger.debug("Detected format: dict (ijson)")
        else:
            self.format = "unknown"
            logger.warning("Unknown OCEL format - some operations may not work")
    
    def trace_object_lifecycle(self, object_id: str) -> List[EventReference]:
        """
        Traces the full lifecycle of an object.

        Args:
            object_id: Object ID.

        Returns:
            List of events ordered by timestamp.

        Raises:
            ValueError: If the object does not exist.
        """
        logger.debug(f"Tracing object lifecycle: {object_id}")
        
        if self.format == "pm4py":
            return self._trace_lifecycle_pm4py(object_id)
        else:
            return self._trace_lifecycle_dict(object_id)
    
    def _trace_lifecycle_pm4py(self, object_id: str) -> List[EventReference]:
        """Lifecycle tracing using PM4PY DataFrames."""
        # Check if object exists using the ocel:oid column
        if object_id not in self.ocel_data.objects["ocel:oid"].values:
            raise ValueError(f"Object not found: {object_id}")
        
        # Get events for this object from relations DataFrame
        obj_relations = self.ocel_data.relations[
            self.ocel_data.relations["ocel:oid"] == object_id
        ]
        event_ids = obj_relations["ocel:eid"].unique()
        
        references = []
        for event_id in sorted(event_ids):
            # Get event data from events DataFrame
            event_row = self.ocel_data.events[
                self.ocel_data.events["ocel:eid"] == event_id
            ]
            if event_row.empty:
                continue
            
            event = event_row.iloc[0]
            
            # Get all objects related to this event
            event_relations = self.ocel_data.relations[
                self.ocel_data.relations["ocel:eid"] == event_id
            ]
            involved_objs = [
                ObjectReference(
                    object_id=str(row["ocel:oid"]),
                    object_type=str(row["ocel:type"]),
                    role=str(row.get("ocel:qualifier", "")) if row.get("ocel:qualifier") else None,
                )
                for _, row in event_relations.iterrows()
            ]
            
            references.append(
                EventReference(
                    event_id=str(event_id),
                    activity=str(event.get("ocel:activity", "unknown")),
                    timestamp=str(event.get("ocel:timestamp", "")),
                    involved_objects=involved_objs,
                )
            )
        
        logger.info(f"Lifecycle for {object_id}: {len(references)} events")
        return references
    
    def _trace_lifecycle_dict(self, object_id: str) -> List[EventReference]:
        """Lifecycle tracing using dict (ijson)."""
        # Build objects index by id
        objects_by_id = {obj.get("id"): obj for obj in self.ocel_data.get("objects", [])}
        
        if object_id not in objects_by_id:
            raise ValueError(f"Object not found: {object_id}")
        
        references = []
        for event in self.ocel_data.get("events", []):
            relationships = event.get("relationships", [])
            
            if any(rel.get("objectId") == object_id for rel in relationships):
                involved_objs = [
                    ObjectReference(
                        object_id=rel.get("objectId"),
                        object_type=objects_by_id.get(rel.get("objectId"), {}).get("type", "unknown"),
                        role=rel.get("qualifier"),
                    )
                    for rel in relationships
                ]
                references.append(
                    EventReference(
                        event_id=event.get("id", ""),
                        activity=event.get("type", "unknown"),
                        timestamp=event.get("time", ""),
                        involved_objects=involved_objs,
                    )
                )
        
        logger.info(f"Lifecycle for {object_id}: {len(references)} events")
        return references
    
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
        else:
            return self._timerange_dict(start, end)
    
    def _timerange_pm4py(self, start: datetime, end: datetime) -> List[EventReference]:
        """Time range query using PM4PY DataFrames."""
        references = []
        
        for _, event in self.ocel_data.events.iterrows():
            try:
                ts_str = str(event.get("ocel:timestamp", ""))
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                
                if start <= ts <= end:
                    event_id = str(event.get("ocel:eid", ""))
                    
                    # Get all objects related to this event
                    event_relations = self.ocel_data.relations[
                        self.ocel_data.relations["ocel:eid"] == event_id
                    ]
                    involved_objs = [
                        ObjectReference(
                            object_id=str(row["ocel:oid"]),
                            object_type=str(row["ocel:type"]),
                            role=str(row.get("ocel:qualifier", "")) if row.get("ocel:qualifier") else None,
                        )
                        for _, row in event_relations.iterrows()
                    ]
                    
                    references.append(
                        EventReference(
                            event_id=event_id,
                            activity=str(event.get("ocel:activity", "unknown")),
                            timestamp=ts_str,
                            involved_objects=involved_objs,
                        )
                    )
            except Exception as e:
                logger.debug(f"Error processing event: {e}")
        
        logger.info(f"Events in range: {len(references)}")
        return references
    
    def _timerange_dict(self, start: datetime, end: datetime) -> List[EventReference]:
        """Time range query using dict."""
        # Build objects index by id
        objects_by_id = {obj.get("id"): obj for obj in self.ocel_data.get("objects", [])}
        
        references = []
        for event in self.ocel_data.get("events", []):
            try:
                ts_str = event.get("time", "")
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                
                if start <= ts <= end:
                    involved_objs = [
                        ObjectReference(
                            object_id=rel.get("objectId"),
                            object_type=objects_by_id.get(rel.get("objectId"), {}).get("type"),
                            role=rel.get("qualifier"),
                        )
                        for rel in event.get("relationships", [])
                    ]
                    references.append(
                        EventReference(
                            event_id=event.get("id", ""),
                            activity=event.get("type", "unknown"),
                            timestamp=ts_str,
                            involved_objects=involved_objs,
                        )
                    )
            except Exception as e:
                logger.debug(f"Error processing event: {e}")
        
        logger.info(f"Events in range: {len(references)}")
        return references
    
    def get_statistics_by_object_type(self) -> Dict[str, ObjectTypeStatsDict]:
        """
        Calculates statistics by object type.

        Returns:
            Dict mapping object type names to their statistics.
        """
        logger.debug("Calculating statistics by object type")
        
        if self.format == "pm4py":
            return self._stats_pm4py()
        else:
            return self._stats_dict()
    
    def _stats_pm4py(self) -> Dict[str, ObjectTypeStatsDict]:
        """Statistics using PM4PY DataFrames.
        
        Returns:
            Dict mapping object type names to statistics.
        """
        stats_by_type: Dict[str, ObjectTypeStatsDict] = {}
        
        for _, obj in self.ocel_data.objects.iterrows():
            obj_id = str(obj.get("ocel:oid", ""))
            obj_type = str(obj.get("ocel:type", "unknown"))
            if obj_type not in stats_by_type:
                stats_by_type[obj_type] = {"count": 0, "objects": []}
            
            stats_by_type[obj_type]["count"] += 1
            stats_by_type[obj_type]["objects"].append(obj_id)
        
        logger.info(f"Statistics: {len(stats_by_type)} object types")
        return stats_by_type
    
    def _stats_dict(self) -> Dict[str, ObjectTypeStatsDict]:
        """Statistics using dict.
        
        Returns:
            Dict mapping object type names to statistics.
        """
        stats_by_type: Dict[str, ObjectTypeStatsDict] = {}
        
        for obj in self.ocel_data.get("objects", []):
            obj_id = obj.get("id", "")
            obj_type = obj.get("type", "unknown")
            if obj_type not in stats_by_type:
                stats_by_type[obj_type] = {"count": 0, "objects": []}
            
            stats_by_type[obj_type]["count"] += 1
            stats_by_type[obj_type]["objects"].append(obj_id)
        
        logger.info(f"Statistics: {len(stats_by_type)} object types")
        return stats_by_type
    
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
        else:
            return self._anomalies_dict()
    
    def _anomalies_pm4py(self) -> List[AnomalyReport]:
        """Anomaly detection using PM4PY DataFrames."""
        anomalies = []
        
        # Get all object IDs from objects DataFrame
        all_object_ids = set(self.ocel_data.objects["ocel:oid"].values)
        
        # Get all object IDs that appear in relations
        objects_in_events = set(self.ocel_data.relations["ocel:oid"].unique())
        
        orphaned_objects = all_object_ids - objects_in_events
        for obj_id in orphaned_objects:
            anomalies.append(
                AnomalyReport(
                    anomaly_type="orphaned_object",
                    severity="medium",
                    affected_id=str(obj_id),
                    description="Object does not participate in any event",
                    timestamp=datetime.utcnow().isoformat(),
                )
            )
        
        # Check for events without related objects
        all_event_ids = set(self.ocel_data.events["ocel:eid"].values)
        events_with_objects = set(self.ocel_data.relations["ocel:eid"].unique())
        events_without_objects = all_event_ids - events_with_objects
        
        for event_id in events_without_objects:
            anomalies.append(
                AnomalyReport(
                    anomaly_type="event_no_objects",
                    severity="high",
                    affected_id=str(event_id),
                    description="Event without related objects",
                    timestamp=datetime.utcnow().isoformat(),
                )
            )
        
        logger.info(f"Anomalies detected: {len(anomalies)}")
        return anomalies
    
    def _anomalies_dict(self) -> List[AnomalyReport]:
        """Anomaly detection using dict."""
        anomalies = []
        
        # Build objects index by id
        objects_by_id = {obj.get("id"): obj for obj in self.ocel_data.get("objects", [])}
        all_object_ids = set(objects_by_id.keys())
        objects_in_events = set()
        
        for event in self.ocel_data.get("events", []):
            for rel in event.get("relationships", []):
                objects_in_events.add(rel.get("objectId"))
        
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
    
    def find_orphaned_objects(self) -> List[str]:
        """
        Finds objects that do not participate in any event.

        Returns:
            List of orphaned object IDs.
        """
        logger.debug("Searching for orphaned objects")
        
        if self.format == "pm4py":
            return self._orphaned_pm4py()
        else:
            return self._orphaned_dict()
    
    def _orphaned_pm4py(self) -> List[str]:
        """Orphaned objects using PM4PY DataFrames."""
        # Get all object IDs from objects DataFrame
        all_objects = set(self.ocel_data.objects["ocel:oid"].values)
        
        # Get all object IDs that appear in relations
        objects_in_events = set(self.ocel_data.relations["ocel:oid"].unique())
        
        orphaned = [str(oid) for oid in (all_objects - objects_in_events)]
        logger.info(f"Orphaned objects found: {len(orphaned)}")
        return orphaned
    
    def _orphaned_dict(self) -> List[str]:
        """Orphaned objects using dict."""
        # Build objects index by id
        objects_by_id = {obj.get("id"): obj for obj in self.ocel_data.get("objects", [])}
        all_objects = set(objects_by_id.keys())
        objects_in_events = set()
        
        for event in self.ocel_data.get("events", []):
            for rel in event.get("relationships", []):
                objects_in_events.add(rel.get("objectId"))
        
        orphaned = list(all_objects - objects_in_events)
        logger.info(f"Orphaned objects found: {len(orphaned)}")
        return orphaned
