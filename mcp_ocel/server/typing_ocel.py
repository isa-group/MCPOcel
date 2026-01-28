"""Generic types and dataclasses for OCEL MCP responses.
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, TypedDict
from datetime import datetime

class EventReferenceDict(TypedDict):
    """Verifiable reference to an OCEL event."""
    event_id: str
    activity: str
    timestamp: str
    involved_objects: List[Dict[str, str]]
    hash: str


class ObjectReferenceDict(TypedDict):
    """Verifiable reference to an OCEL object."""
    object_id: str
    object_type: str
    role: Optional[str]


@dataclass
class ObjectReference:
    """Reference to an object within an event."""
    object_id: str
    object_type: str
    role: Optional[str] = None

    def to_dict(self) -> ObjectReferenceDict:
        return {
            "object_id": self.object_id,
            "object_type": self.object_type,
            "role": self.role,
        }


@dataclass
class EventReference:
    """Verifiable reference to an OCEL event."""
    event_id: str
    activity: str
    timestamp: str
    involved_objects: List[ObjectReference]

    def to_dict(self) -> EventReferenceDict:
        return {
            "event_id": self.event_id,
            "activity": self.activity,
            "timestamp": self.timestamp,
            "involved_objects": [obj.to_dict() for obj in self.involved_objects],
            "hash": self.compute_hash(),
        }

    def compute_hash(self) -> str:
        """Computes SHA256 of content for verification."""
        import hashlib

        object_ids = sorted([obj.object_id for obj in self.involved_objects])
        content = f"{self.event_id}:{self.timestamp}:{','.join(object_ids)}"
        return hashlib.sha256(content.encode()).hexdigest()


@dataclass
class UnifiedMCPResponse:
    """Unified MCP response: references + markdown + visualization."""
    references: List[Dict[str, Any]]

    summary: str

    visualization: Optional[Dict[str, Any]] = None

    metadata: Optional[Dict[str, Any]] = None

    verification_hash: str = ""
    generated_at: str = ""

    def __post_init__(self):
        """Initializes computed fields."""
        if not self.generated_at:
            self.generated_at = datetime.utcnow().isoformat()
        if not self.verification_hash:
            self.verification_hash = self._compute_verification_hash()

    def _compute_verification_hash(self) -> str:
        """Computes integrity hash for entire response."""
        import hashlib
        import json

        content = json.dumps(
            {
                "references_count": len(self.references),
                "summary_hash": hashlib.sha256(self.summary.encode()).hexdigest(),
                "generated_at": self.generated_at,
            },
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Converts to JSON-serializable dictionary."""
        return {
            "references": self.references,
            "summary": self.summary,
            "visualization": self.visualization,
            "metadata": self.metadata or {},
            "verification_hash": self.verification_hash,
            "generated_at": self.generated_at,
        }


@dataclass
class OCELStatistics:
    """General statistics for an OCEL."""
    total_events: int
    total_objects: int
    event_types: List[str]
    object_types: List[str]
    object_type_distribution: Dict[str, int]
    event_type_distribution: Dict[str, int]
    time_range_start: Optional[str] = None
    time_range_end: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProcessVariant:
    """Process variant (sequence of activities)."""
    variant_id: str
    activity_sequence: List[str]
    frequency: int
    percentage: float
    sample_event_ids: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnomalyReport:
    """Report of a detected anomaly."""
    anomaly_type: str  # "orphaned_object", "missing_ref", "outlier", etc.
    severity: str  # "low", "medium", "high"
    affected_id: str  # event_id or object_id
    description: str
    timestamp: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
