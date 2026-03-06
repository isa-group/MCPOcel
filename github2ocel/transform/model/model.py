from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from shared.utils.time import to_iso8601

@dataclass
class RepoStats:
   issues:       int = 0
   pull_requests: int = 0
   discussions:  int = 0
   releases:     int = 0
   milestones:   int = 0
   tags:         int = 0
   branches:     int = 0
   commits:      int = 0
   reviews_est:  int = 0   # estimated: prs * avg_reviews_per_pr

@dataclass
class PageSizes:
   milestones:    int = 100
   branches:      int = 100
   tags:          int = 100
   issues:        int = 50
   pull_requests: int = 20
   commits:       int = 50
   releases:      int = 50
   discussions:   int = 50

   # Per-PR nested (used only for overflow pagination)
   pr_reviews:    int = 30
   pr_comments:   int = 50
   pr_commits:    int = 100
   pr_timeline:   int = 50

   # Per-Issue nested
   issue_comments: int = 50
   issue_timeline: int = 100

@dataclass
class EventType:
    def __init__(self, name: str, attributes: Dict[str, str] = None):
        self.name = name
        self.attributes = attributes  # {attr_name: attr_type}

@dataclass
class ObjectType:
    def __init__(self, name: str, attributes: Dict[str, str] = None):
        self.name = name
        self.attributes = attributes  # {attr_name: attr_type}

@dataclass
class Event:
    def __init__(
        self,
        event_id: str,
        event_type: str,
        time: Any,
        attributes: Dict[str, Any] = None
        ):
            self.id = event_id
            self.type = event_type
            self.time = to_iso8601(time)
            self.attributes = attributes or {}
            self.relationships = []  # (object_id, qualifier)

    def add_rel(self, object_id: str, qualifier: str = None):
        """Helper for quickly adding relationships"""
        if qualifier is None:
            qualifier = "relates_to"
        self.relationships.append((object_id, qualifier))

@dataclass
class ObjectSnapshot:
    def __init__(
        self,
        time: Any,
        attributes: Dict[str, Any],
        changed_field: str = None):
            self.time = to_iso8601(time)
            self.changed_field = changed_field
            self.attributes = attributes

@dataclass
class ObjectInstance:
    def __init__(self, object_id: str, object_type: str):
        self.id = object_id
        self.type = object_type
        self.snapshots: List[ObjectSnapshot] = []
        self.related_objects: List[tuple[str, str]] = []

    def add_snapshot(self, time: Any, attributes: Dict[str, Any]):
        self.snapshots.append(ObjectSnapshot(time, attributes))

    def add_rel(self, target_id: str, qualifier: str = None):
        if qualifier is None:
            qualifier = "relates_to"

        self.related_objects.append((target_id, qualifier))

@dataclass
class ExtractionRange:
    since: Optional[str] = None  # ISO format
    until: Optional[str] = None  # ISO format

    @property
    def is_active(self) -> bool:
        return self.since is not None

@dataclass
class ExtractionContext:
    owner: str
    repo: str
    range: ExtractionRange
    page_sizes: PageSizes