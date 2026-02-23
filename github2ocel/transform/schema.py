"""GitHub-specific OCEL schema definitions.

Contains object type definitions and attribute type hints
specific to the GitHub domain.
"""

from typing import Dict, List, Union, Tuple

# GitHub Object Schema Definitions
# Maps object types to their expected attributes
GITHUB_OBJECT_SCHEMA: Dict[str, List[str]] = {
    "Repository": ["name", "full_name", "visibility"],
    "Issue": ["number", "state", "title", "created_at", "closed_at"],
    "PullRequest": ["number", "merged", "merged_at", "source"],
    "Commit": ["sha", "message", "source"],
    "WorkflowRun": ["run_id", "name", "conclusion", "duration_seconds"],
    "User": ["login"],
    "Branch": ["name"],
    "File": ["path"],
    "Label": ["name", "color"],
    "Release": ["tag_name", "name", "prerelease"],
    "Discussion": ["number", "title", "url", "locked", "category", "reactions_count"],
    "DiscussionComment": ["body_length", "reactions_count"],
}

# GitHub Attribute Type Hints
# Used for validation warnings when types don't match
GITHUB_ATTRIBUTE_TYPES: Dict[str, Union[type, Tuple[type, ...]]] = {
    "number": int,
    "merged": bool,
    "duration_seconds": (int, float),
    "additions": int,
    "deletions": int,
    "files_changed": int,
    "state": str,
    "conclusion": str,
    "color": str,
    "name": str,
    "prerelease": bool,
}
