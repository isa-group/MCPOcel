from typing import Dict, Any
from shared.ocel.builder import OCELBuilder
from shared.ocel.model.models import ObjectInstance
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user, ensure_label
from github2ocel.transform.utils.reactions import parse_reaction_groups
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.mappers.process_comment import map_issue_comment
from shared.logger import get_logger

logger = get_logger(__name__)


def process_issue(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    number = node.get("number")
    if not number:
        logger.warning("[process_issue] Missing number. Skipping.")
        return

    obj_id = make_id(repo_id, "issue", number)
    created_at = safe_timestamp(node.get("createdAt"))

    body_text = node.get("bodyText") or ""

    reactions = parse_reaction_groups(node.get("reactionGroups", []))

    # Object: Issue
    obj = ObjectInstance(object_id=obj_id, object_type="Issue")
    obj.add_snapshot(
        time=safe_timestamp(None), # unix epoch OCEL2.0 standard
        attributes={
            "number":             int(number),
            "title":              (node.get("title") or "")[:255],
            "state":              node.get("state", "OPEN"),
            "state_reason":       node.get("stateReason") or "",
            "url":                node.get("url", ""),
            "github_node_id":     node.get("id", ""),
            "updated_at":         safe_timestamp(node.get("updatedAt")),
            "closed_at":          safe_timestamp(node.get("closedAt")) if node.get("closedAt") else None,
            "body_length":        len(body_text),
            "body_text":          body_text[:2000],
            "locked":             1 if node.get("locked") else 0,
            "locked_reason":      node.get("activeLockReason") or "",
            "is_pinned":          1 if node.get("isPinned") else 0,
            "author_association": node.get("authorAssociation", ""),
            "reactions_count":    (node.get("reactions") or {}).get("totalCount", 0),
            "participants_count": (node.get("participants") or {}).get("totalCount", 0),
            "comments_count":     (node.get("comments") or {}).get("totalCount", 0),
            **reactions,
        }
    )

    # O2O: Issue -> Repository
    obj.add_rel(repo_id, "contained_in")

    # O2O: Issue -> Author (User)
    author_login = (node.get("author") or {}).get("login")
    author_id = ensure_user(builder, repo_id, author_login, timestamp=created_at) if author_login else None
    if author_id:
        obj.add_rel(author_id, "created_by")

    # O2O: Issue -> Assignees (User)
    for assignee in (node.get("assignees") or {}).get("nodes", []):
        a_login = assignee.get("login")
        a_id = ensure_user(builder, repo_id, a_login, timestamp=created_at) if a_login else None
        if a_id:
            obj.add_rel(a_id, "assigned_to")

    # O2O: Issue -> Labels
    for lbl in (node.get("labels") or {}).get("nodes", []):
        lbl_id = ensure_label(builder, repo_id, lbl, timestamp=created_at)
        if lbl_id:
            obj.add_rel(lbl_id, "has_label")

    # O2O: Issue -> Milestone (object already exists from Phase 0)
    milestone = node.get("milestone")
    if milestone and milestone.get("id"):
        ms_id = make_id(repo_id, "milestone", milestone["id"])
        if builder.object_exists(ms_id):
            obj.add_rel(ms_id, "belongs_to_milestone")

    builder.insert_object(obj)

    # Event: IssueOpened
    create_event(
        builder=builder,
        event_type=Activities.ISSUE_OPENED,
        ts=created_at,
        attributes={"source": "graphql"},
        relationships=[
            (obj_id, "subject"),
            (repo_id, "context"),
            (author_id, "actor") if author_id else None,
        ]
    )

    # NOTE: IssueCommentCreated events are NOT mapped here.
    # All comments are fetched and mapped in Phase 2 (fetch_issue_comments)
    # to avoid duplicate events and ensure full pagination coverage.


def process_issue_comment(comment: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Map a single Issue comment to a Comment object + CommentCreated event.
    Called from Phase 2 with fully paginated comment nodes.
    The comment dict must have "__issue_number" injected by the fetcher.
    """
    issue_number = comment.get("__issue_number")
    if not issue_number:
        return

    issue_id = make_id(repo_id, "issue", issue_number)
    if not builder.object_exists(issue_id):
        return

    map_issue_comment(comment, builder, repo_id, issue_id)