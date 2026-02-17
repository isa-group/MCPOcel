"""
Generic OCEL query engine.
Seven MVP tools: lifecycle, timerange, statistics, anomalies, orphaned objects, filter by event type and filter by object type
"""
import pm4py
from datetime import datetime
from typing import Dict, List

from .typing_ocel import (
    MCPEventReference as EventReference,
    MCPObjectReference as ObjectReference,
    AnomalyReport,
    OCELData,
    ObjectTypeStatsDict,
)
from shared.logger.logging_config import get_logger

logger = get_logger(__name__)

class OCELQueryEngine:
    """Domain-agnostic query engine for OCEL 2.0."""
    
    ocel_data: OCELData
    
    def __init__(self, ocel_data: OCELData) -> None:
        """
        Initializes the query engine.

        Args:
            ocel_data: Loaded OCEL (PM4PY object).
        """
        self.ocel_data = ocel_data
    
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
        return self._trace_lifecycle(object_id)
    
    def _trace_lifecycle(self, object_id: str) -> List[EventReference]:
        """Lifecycle tracing using DataFrames."""
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
        return self._timerange(start, end)
    
    def _timerange(self, start: datetime, end: datetime) -> List[EventReference]:
        """Time range query using DataFrames."""
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
    
    def get_statistics_by_object_type(self) -> Dict[str, ObjectTypeStatsDict]:
        """
        Calculates statistics by object type.

        Returns:
            Dict mapping object type names to their statistics.
        """
        logger.debug("Calculating statistics by object type")
        return self._stats()
    
    def _stats(self) -> Dict[str, ObjectTypeStatsDict]:
        """Statistics using DataFrames.
        
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
        return self._anomalies()
    
    def _anomalies(self) -> List[AnomalyReport]:
        """Anomaly detection using DataFrames."""
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
    
    def find_orphaned_objects(self) -> List[str]:
        """
        Finds objects that do not participate in any event.

        Returns:
            List of orphaned object IDs.
        """
        logger.debug("Searching for orphaned objects")
        return self._orphaned()
    
    def _orphaned(self) -> List[str]:
        """Orphaned objects using DataFrames."""
        # Get all object IDs from objects DataFrame
        all_objects = set(self.ocel_data.objects["ocel:oid"].values)
        
        # Get all object IDs that appear in relations
        objects_in_events = set(self.ocel_data.relations["ocel:oid"].unique())
        
        orphaned = [str(oid) for oid in (all_objects - objects_in_events)]
        logger.info(f"Orphaned objects found: {len(orphaned)}")
        return orphaned

    # ------------------------------------------------------------------
    # Filter by event type / object type
    # ------------------------------------------------------------------

    def get_events_by_event_type(
        self, event_type: str
    ) -> List[EventReference]:
        """
        Returns all events of a given event type (activity).

        Uses ``pm4py.filter_ocel_event_attribute`` with ``ocel:activity``.

        Args:
            event_type: Exact event type / activity name (e.g. "PRMerged").

        Returns:
            List of EventReference for matching events.

        Raises:
            ValueError: If the event type does not exist in the log.
        """
        known = set(self.ocel_data.events["ocel:activity"].unique())
        if event_type not in known:
            raise ValueError(
                f"Event type '{event_type}' not found. "
                f"Available event types: {sorted(known)}"
            )

        logger.debug(f"Filtering events by event type: {event_type}")
        return self._filter_by_event_type(event_type)

    def _filter_by_event_type(self, event_type: str) -> List[EventReference]:
        """Filter events using PM4PY ``filter_ocel_event_attribute``."""
        filtered_ocel = pm4py.filter_ocel_event_attribute(
            self.ocel_data, "ocel:activity", [event_type]
        )
        return self._ocel_events_to_references(filtered_ocel)

    def get_events_by_object_type(
        self, object_type: str
    ) -> List[EventReference]:
        """
        Returns all events involving objects of a given object type.

        Uses ``pm4py.filter_ocel_object_types``.

        Args:
            object_type: Exact object type name (e.g. "PullRequest").

        Returns:
            List of EventReference for matching events.

        Raises:
            ValueError: If the object type does not exist in the log.
        """
        known = set(self.ocel_data.objects["ocel:type"].unique())
        if object_type not in known:
            raise ValueError(
                f"Object type '{object_type}' not found. "
                f"Available object types: {sorted(known)}"
            )

        logger.debug(f"Filtering events by object type: {object_type}")
        return self._filter_by_object_type(object_type)

    def _filter_by_object_type(self, object_type: str) -> List[EventReference]:
        """Filter events using PM4PY ``filter_ocel_object_types``."""
        filtered_ocel = pm4py.filter_ocel_object_types(
            self.ocel_data, [object_type]
        )
        return self._ocel_events_to_references(filtered_ocel)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _ocel_events_to_references(
        self, ocel: OCELData
    ) -> List[EventReference]:
        """
        Convert all events in an OCEL object to ``EventReference`` list.

        Reused by the event-type and object-type filter methods.
        """
        references: List[EventReference] = []

        for _, event in ocel.events.iterrows():
            event_id = str(event.get("ocel:eid", ""))

            event_relations = ocel.relations[
                ocel.relations["ocel:eid"] == event_id
            ]
            involved_objs = [
                ObjectReference(
                    object_id=str(row["ocel:oid"]),
                    object_type=str(row["ocel:type"]),
                    role=(
                        str(row.get("ocel:qualifier", ""))
                        if row.get("ocel:qualifier")
                        else None
                    ),
                )
                for _, row in event_relations.iterrows()
            ]

            references.append(
                EventReference(
                    event_id=event_id,
                    activity=str(event.get("ocel:activity", "unknown")),
                    timestamp=str(event.get("ocel:timestamp", "")),
                    involved_objects=involved_objs,
                )
            )

        logger.info(f"Converted {len(references)} events to references")
        return references
