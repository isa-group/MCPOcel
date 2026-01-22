import uuid
import json

class OCELBuilder:
    def __init__(self):
        self.ocel = {
            "ocel:global-log": {},
            "ocel:version": "2.0",
            "ocel:ordering": "timestamp",
            "ocel:attribute-names": [
                "additions", "deletions", "state", "conclusion", "duration_seconds"
            ],
            "ocel:object-types": [],
            "ocel:event-types": [],
            "ocel:objects": {},
            "ocel:events": {}
        }
        self._init_types()

    def _init_types(self):
        # Explicit definition of the domain model objects
        types = ["Repository", "Issue", "PullRequest", "Commit", "WorkflowRun", "User", "Branch", "File"]
        for t in types:
            self.ocel["ocel:object-types"].append({"ocel:type": t, "ocel:attributes": []})

    def add_object(self, obj_id, obj_type, attributes):
        if obj_id not in self.ocel["ocel:objects"]:
            self.ocel["ocel:objects"][obj_id] = {
                "ocel:type": obj_type,
                "ocel:ovmap": attributes
            }

    def add_event(self, activity, timestamp, related_objects, attributes=None):
        event_id = str(uuid.uuid4())
        self.ocel["ocel:events"][event_id] = {
            "ocel:activity": activity,
            "ocel:timestamp": timestamp,
            "ocel:omap": list(set(related_objects)), # Ensure unique references
            "ocel:vmap": attributes or {}
        }

    def export_json(self, filename):
        with open(filename, "w") as f:
            json.dump(self.ocel, f, indent=2)