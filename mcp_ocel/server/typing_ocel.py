"""Generic types and dataclasses for OCEL MCP responses.

This module serves as the central hub for all type definitions used across
the MCP OCEL server and client. It includes TypedDicts for tool responses,
dataclasses for domain objects, and type aliases for common patterns.
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, TypedDict, Union, Generator
from typing_extensions import NotRequired
from datetime import datetime


# =============================================================================
# Type Aliases for External Dependencies
# =============================================================================

# PM4PY OCEL object or dict-based OCEL - treated as Any since external
OCELData = Any

# Event stream generator type for ijson streaming
EventStreamGenerator = Generator[List[Dict[str, Any]], None, None]

# Logging module type
Logger = Any


# =============================================================================
# Base OCEL Dataclasses
# =============================================================================

@dataclass
class EventReference:
    """Reference to a single event with core attributes."""
    id: str
    type: str
    timestamp: str
    related_objects: List[str]
    attributes: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converts to dictionary."""
        return asdict(self)


@dataclass
class ObjectReference:
    """Reference to a single object with core attributes."""
    id: str
    type: str
    attributes: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converts to dictionary."""
        return asdict(self)


@dataclass
class AnomalyReport:
    """Anomaly detection result."""
    anomaly_type: str
    description: str
    severity: str  # "low", "medium", "high"
    affected_entities: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Converts to dictionary."""
        return asdict(self)


# Type aliases
EventDict = Dict[str, Any]
ObjectDict = Dict[str, Any]
ObjectTypeStatsDict = Dict[str, Any]


# =============================================================================
# Base TypedDicts for Common Structures
# =============================================================================

class ErrorResponse(TypedDict):
    """Base error response that can be included in any tool response."""
    error: str


class VisualizationDict(TypedDict, total=False):
    """Visualization data returned by visualization tools."""
    format: str  # "svg" or "png"
    content: NotRequired[str]  # SVG content
    data_base64: NotRequired[str]  # PNG base64 data
    type: str  # "visualization"
    metadata: NotRequired[Dict[str, Any]]


class MetadataDict(TypedDict, total=False):
    """Common metadata structure."""
    time_unit: NotRequired[str]
    object_type_filter: NotRequired[Optional[str]]
    total_events: NotRequired[int]
    total_objects: NotRequired[int]


# =============================================================================
# DFG (Directly Follows Graph) Types
# =============================================================================

class DFGEdgeDict(TypedDict):
    """A single edge in a DFG."""
    source: str
    target: str
    frequency: int


class DFGStartActivityDict(TypedDict):
    """Start activity in a DFG."""
    activity: str
    frequency: int


class DFGDict(TypedDict, total=False):
    """DFG structure returned by process mining engine."""
    edges: List[DFGEdgeDict]
    start_activities: NotRequired[List[DFGStartActivityDict]]


# =============================================================================
# Petri Net Types
# =============================================================================

class PetriNetDict(TypedDict):
    """Petri Net structure returned by process mining engine."""
    places: int
    transitions: int
    arcs: int
    initial_marking: str
    final_marking: str


# =============================================================================
# Performance Metrics Types
# =============================================================================

class TransitionStatsDict(TypedDict):
    """Statistics for a single transition."""
    count: int
    avg_seconds: float
    min_seconds: float
    max_seconds: float
    median_seconds: float
    std_seconds: float


class PerformanceMetricsDict(TypedDict, total=False):
    """Performance metrics returned by process mining engine."""
    time_unit: str
    transitions: Dict[str, TransitionStatsDict]
    total_transitions_analyzed: int
    error: NotRequired[str]


# =============================================================================
# Bottleneck Detection Types
# =============================================================================

class BottleneckInfoDict(TypedDict):
    """Information about a detected bottleneck."""
    transition: str
    avg_seconds: float
    max_seconds: float
    count: int
    severity: str  # "high" or "medium"


class BottleneckResultDict(TypedDict, total=False):
    """Bottleneck detection result."""
    bottlenecks: List[BottleneckInfoDict]
    threshold_percentile: float
    threshold_seconds: NotRequired[float]
    time_unit: str
    total_transitions: NotRequired[int]
    error: NotRequired[str]


# =============================================================================
# Conformance Checking Types
# =============================================================================

class DeviationDict(TypedDict):
    """A conformance deviation."""
    object_id: str
    deviation: str
    position: int


class ConformanceModelDict(TypedDict):
    """Model info in conformance result."""
    places: int
    transitions: int


class ConformanceResultDict(TypedDict, total=False):
    """Conformance checking result."""
    fitness_score: float
    fitness_percentage: float
    sample_size: int
    conformant_traces: int
    deviations: List[DeviationDict]
    total_deviations: int
    model: NotRequired[ConformanceModelDict]
    error: NotRequired[str]


# =============================================================================
# Object Interactions Types
# =============================================================================

class ObjectInteractionDict(TypedDict):
    """A single object type interaction."""
    type_1: str
    type_2: str
    co_occurrences: int


class ObjectInteractionsResultDict(TypedDict, total=False):
    """Object interactions analysis result."""
    object_types: List[str]
    co_occurrence_matrix: Dict[str, Dict[str, int]]
    top_interactions: List[ObjectInteractionDict]
    total_pairs_analyzed: int
    error: NotRequired[str]


# =============================================================================
# Process Variants Types
# =============================================================================

class VariantDict(TypedDict, total=False):
    """A single process variant."""
    activity_sequence: List[str]
    frequency: int
    sample_objects: NotRequired[List[str]]
    sample_events: NotRequired[List[str]]


# =============================================================================
# Social Network Types
# =============================================================================

class SocialNetworkEdgeDict(TypedDict):
    """An edge in the social network."""
    source: str
    target: str
    weight: int


class SocialNetworkResultDict(TypedDict, total=False):
    """Social network discovery result."""
    nodes: List[str]
    edges: List[SocialNetworkEdgeDict]
    total_nodes: int
    total_edges: int
    resource_attribute: str
    error: NotRequired[str]
    available_attributes: NotRequired[List[str]]


# =============================================================================
# Statistics Types
# =============================================================================

class ObjectTypeStatsDict(TypedDict):
    """Statistics for a single object type."""
    count: int
    objects: List[str]


class StatsByObjectTypeDict(TypedDict):
    """Statistics grouped by object type."""
    # Keys are object type names, values are ObjectTypeStatsDict
    pass  # This is a dynamic dict, use Dict[str, ObjectTypeStatsDict] in practice


class OCELStatsDict(TypedDict, total=False):
    """Basic OCEL statistics."""
    total_events: int
    total_objects: int
    object_types: int
    event_types: int
    error: NotRequired[str]


# =============================================================================
# Search/Retrieval Types
# =============================================================================

class SearchResultItemDict(TypedDict, total=False):
    """A single search result item."""
    content: str
    chunk_type: str
    path: str
    score: float
    metadata: NotRequired[Dict[str, Any]]


class SearchResultDict(TypedDict, total=False):
    """Search result from retrieval engine."""
    query: str
    total_results: int
    results: List[SearchResultItemDict]
    error: NotRequired[str]
    fallback: NotRequired[str]


# =============================================================================
# Tool List Types
# =============================================================================

class ToolParameterDict(TypedDict, total=False):
    """Parameter definition for a tool."""
    type: str
    description: str
    title: str


class InputSchemaDict(TypedDict, total=False):
    """MCP standard inputSchema format."""
    type: str
    properties: Dict[str, ToolParameterDict]
    required: List[str]


class ToolInfoDict(TypedDict, total=False):
    """Information about an MCP tool (MCP standard format)."""
    name: str
    description: str
    inputSchema: InputSchemaDict
    metadata: NotRequired[Dict[str, Any]]


class ListToolsResponseDict(TypedDict):
    """Response from list_available_tools."""
    tools: List[ToolInfoDict]
    total_count: int
    metadata: Dict[str, Any]


# =============================================================================
# MCP Tool Response Types (for each specific tool)
# =============================================================================

class TraceLifecycleResponseDict(TypedDict, total=False):
    """Response from trace_object_lifecycle tool."""
    references: List[Dict[str, Any]]
    summary: str
    visualization: NotRequired[VisualizationDict]
    metadata: Dict[str, Any]
    verification_hash: str
    generated_at: str
    error: NotRequired[str]
    object_id: NotRequired[str]


class TimeRangeQueryResponseDict(TypedDict, total=False):
    """Response from query_events_by_timerange tool."""
    references: List[Dict[str, Any]]
    summary: str
    visualization: NotRequired[VisualizationDict]
    metadata: Dict[str, Any]
    verification_hash: str
    generated_at: str
    error: NotRequired[str]


class StatisticsResponseDict(TypedDict, total=False):
    """Response from get_statistics_by_object_type tool."""
    references: List[Dict[str, Any]]
    summary: str
    visualization: NotRequired[VisualizationDict]
    metadata: Dict[str, Any]
    verification_hash: str
    generated_at: str
    error: NotRequired[str]


class AnomaliesResponseDict(TypedDict, total=False):
    """Response from detect_anomalies tool."""
    references: List[Dict[str, Any]]
    summary: str
    visualization: NotRequired[VisualizationDict]
    metadata: Dict[str, Any]
    verification_hash: str
    generated_at: str
    error: NotRequired[str]


class OrphanedObjectsResponseDict(TypedDict, total=False):
    """Response from find_orphaned_objects tool."""
    references: List[Dict[str, Any]]
    summary: str
    visualization: NotRequired[VisualizationDict]
    metadata: Dict[str, Any]
    verification_hash: str
    generated_at: str
    error: NotRequired[str]


class DFGResponseDict(TypedDict, total=False):
    """Response from discover_dfg tool."""
    references: List[Dict[str, Any]]
    summary: str
    visualization: NotRequired[VisualizationDict]
    metadata: Dict[str, Any]
    verification_hash: str
    generated_at: str
    error: NotRequired[str]
    object_type: NotRequired[str]


class PetriNetResponseDict(TypedDict, total=False):
    """Response from discover_petri_net tool."""
    references: List[Dict[str, Any]]
    summary: str
    visualization: NotRequired[VisualizationDict]
    metadata: Dict[str, Any]
    verification_hash: str
    generated_at: str
    error: NotRequired[str]
    object_type: NotRequired[str]


class VariantsResponseDict(TypedDict, total=False):
    """Response from get_process_variants tool."""
    references: List[Dict[str, Any]]
    summary: str
    visualization: NotRequired[VisualizationDict]
    metadata: Dict[str, Any]
    verification_hash: str
    generated_at: str
    error: NotRequired[str]
    object_type: NotRequired[str]


class PerformanceResponseDict(TypedDict, total=False):
    """Response from get_performance_metrics tool."""
    references: List[Dict[str, Any]]
    summary: str
    visualization: NotRequired[VisualizationDict]
    metadata: Dict[str, Any]
    verification_hash: str
    generated_at: str
    error: NotRequired[str]
    object_type: NotRequired[str]


class BottlenecksResponseDict(TypedDict, total=False):
    """Response from detect_bottlenecks tool."""
    references: List[Dict[str, Any]]
    summary: str
    visualization: NotRequired[VisualizationDict]
    metadata: Dict[str, Any]
    verification_hash: str
    generated_at: str
    error: NotRequired[str]
    object_type: NotRequired[str]


class ConformanceResponseDict(TypedDict, total=False):
    """Response from check_conformance tool."""
    references: List[Dict[str, Any]]
    summary: str
    visualization: NotRequired[VisualizationDict]
    metadata: Dict[str, Any]
    verification_hash: str
    generated_at: str
    error: NotRequired[str]
    object_type: NotRequired[str]


class InteractionsResponseDict(TypedDict, total=False):
    """Response from analyze_object_interactions tool."""
    references: List[Dict[str, Any]]
    summary: str
    visualization: NotRequired[VisualizationDict]
    metadata: Dict[str, Any]
    verification_hash: str
    generated_at: str
    error: NotRequired[str]


class ResourceAttributesResponseDict(TypedDict, total=False):
    """Response from get_available_resource_attributes tool."""
    available_attributes: List[str]
    total_count: int
    hint: str
    error: NotRequired[str]


class SocialNetworkResponseDict(TypedDict, total=False):
    """Response from discover_social_network tool."""
    references: List[Dict[str, Any]]
    summary: str
    visualization: NotRequired[VisualizationDict]
    metadata: Dict[str, Any]
    verification_hash: str
    generated_at: str
    error: NotRequired[str]
    resource_attribute: NotRequired[str]


# =============================================================================
# Union Type for All Tool Responses
# =============================================================================

ToolResponse = Union[
    TraceLifecycleResponseDict,
    TimeRangeQueryResponseDict,
    StatisticsResponseDict,
    AnomaliesResponseDict,
    OrphanedObjectsResponseDict,
    DFGResponseDict,
    PetriNetResponseDict,
    VariantsResponseDict,
    PerformanceResponseDict,
    BottlenecksResponseDict,
    ConformanceResponseDict,
    InteractionsResponseDict,
    ResourceAttributesResponseDict,
    SocialNetworkResponseDict,
    SearchResultDict,
    ListToolsResponseDict,
    ErrorResponse,
]


# =============================================================================
# Client Types
# =============================================================================

class ChatMessageDict(TypedDict):
    """A chat message for LLM providers."""
    role: str  # "system", "user", "assistant"
    content: str


# =============================================================================
# Generator Types
# =============================================================================

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
class MCPObjectReference:
    """MCP-specific reference to an object within an event with role."""
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
class MCPEventReference:
    """MCP-specific verifiable reference to an OCEL event with hash."""
    event_id: str
    activity: str
    timestamp: str
    involved_objects: List[MCPObjectReference]

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
