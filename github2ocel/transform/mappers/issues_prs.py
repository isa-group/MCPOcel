import logging
from typing import Dict, Any, Tuple
from github2ocel.transform.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id
from github2ocel.transform.utils.ensure import ensure_user, is_pull_request, get_node_type
from github2ocel.transform.utils.activity import Activities

logger = logging.getLogger(__name__)

def is_pull_request(node: Dict[str, Any]) -> bool:
    """Single contract based on fetcher tagging."""
    return node.get("__type") == "PullRequest"


def process_base_node(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> Tuple[str, bool]:
    """
    Creates the base object (Issue or PullRequest) and returns its ID and type.
    """
    node_type = get_node_type(node)
    is_pr = is_pull_request(node)

    try:
        # Generate a stable ID based on the PR/Issue number
        obj_id = make_id(repo_id, "pr" if is_pr else "issue", node["number"])
    except (KeyError, ValueError) as e:
        logger.error(f"Error generating ID for {node_type}: {e}")
        raise

    # Base attributes
    attrs = {
        "number": node["number"],
        "title": node.get("title", ""),
        "state": node.get("state", "OPEN")
    }

    # PR-specific attributes
    if is_pr:
        attrs.update({
            "merged": node.get("merged", False),
            "head_ref": node.get("headRefName", ""),
            "base_ref": node.get("baseRefName", ""),
            "is_draft": node.get("isDraft", False)
        })

    builder.add_object(obj_id, node_type, attrs)
    return obj_id, is_pr


def map_main_events(node: Dict[str, Any], builder: OCELBuilder,
                    repo_id: str, obj_id: str, is_pr: bool) -> None:
    """
    Maps the fundamental events: Opened, Closed, and Merged.
    """
    author_id = ensure_user(builder, node.get("author", {}).get("login"))

    # Base event relationships
    rels = [
        builder.rel(obj_id, "target"),
        builder.rel(repo_id, "source")
    ]
    if author_id:
        rels.append(builder.rel(author_id, "author"))

    # Highly reliable metadata (directly observed events)
    obs_meta = {
        "event_class": "observed",
        "source": "github_graphql_api",
        "confidence": "high"
    }

    # 1. Opening Event
    builder.add_event(
        Activities.PR_OPENED if is_pr else Activities.ISSUE_OPENED,
        node["createdAt"],
        rels,
        obs_meta
    )

    # 2. Closing Event
    if node.get("closedAt"):
        builder.add_event(
            Activities.PR_CLOSED if is_pr else Activities.ISSUE_CLOSED,
            node["closedAt"],
            rels,
            obs_meta
        )

    # 3. Merge Event (PRs Only)
    if is_pr and node.get("mergedAt"):
        builder.add_event(
            Activities.PR_MERGED,
            node["mergedAt"],
            rels,
            obs_meta
        )

def map_management_context(node: Dict[str, Any], builder: OCELBuilder, obj_id: str) -> None:
    milestone = node.get("milestone")
    if milestone:
        m_id = f"milestone_{milestone['id']}"
        builder.add_object(m_id, "Milestone", {
            "title": milestone["title"],
            "due_on": milestone.get("dueOn")
        })
        # Link Issue/PR to Milestone
        builder.add_object_relationship(obj_id, m_id, "belongs_to_milestone")