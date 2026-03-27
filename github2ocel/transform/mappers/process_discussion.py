from typing import Dict, Any, Optional

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user, ensure_label
from github2ocel.transform.utils.reactions import parse_reaction_groups
from shared.ocel.model.models import ObjectInstance
from shared.logger import get_logger

logger = get_logger(__name__)


def process_discussion(
    discussion: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
) -> Optional[str]:
    """
    Registers a GitHub Discussion as an OCEL object + creation event.
    Returns the discussion_id, or None if the node is invalid.
    """
    discussion_number = discussion.get("number")
    if discussion_number is None:
        return None

    discussion_id = make_id(repo_id, "discussion", discussion_number)
    ts_created = safe_timestamp(discussion.get("createdAt"))
    body_text = discussion.get("bodyText") or ""

    reactions = parse_reaction_groups(discussion.get("reactionGroups", []))

    # Object: Discussion
    discussion_obj = ObjectInstance(
        object_id=discussion_id,
        object_type="Discussion",
    )
    discussion_obj.add_snapshot(
        time=ts_created,
        attributes={
            "number":          discussion_number,
            "title":           (discussion.get("title") or "")[:255],
            "url":             discussion.get("url", ""),
            "locked":          1 if discussion.get("locked") else 0,
            "category":        (discussion.get("category") or {}).get("name", ""),
            "body_length":     len(body_text),
            "upvote_count":    discussion.get("upvoteCount") or 0,
            "reactions_count": (discussion.get("reactions") or {}).get("totalCount", 0),
            "comments_total":  (discussion.get("comments")  or {}).get("totalCount", 0),
            "updated_at":      safe_timestamp(discussion.get("updatedAt")),
            **reactions,
        }
    )

    # O2O: Discussion -> Repository
    discussion_obj.add_rel(repo_id, "contained_in")

    # O2O: Discussion -> Author
    author_login = (discussion.get("author") or {}).get("login")
    author_id = ensure_user(builder, repo_id, author_login, timestamp=ts_created) if author_login else None
    if author_id:
        discussion_obj.add_rel(author_id, "created_by")

    # O2O: Discussion -> Labels
    for lbl in (discussion.get("labels") or {}).get("nodes") or []:
        if lbl and lbl.get("id"):
            lbl_id = ensure_label(builder, repo_id, lbl, timestamp=ts_created)
            if lbl_id:
                discussion_obj.add_rel(lbl_id, "has_label")

    builder.insert_object(discussion_obj)

    # Event: DiscussionCreated
    create_event(
        builder=builder,
        event_type=Activities.DISCUSSION_CREATED,
        ts=ts_created,
        attributes={"source": "graphql"},
        relationships=[
            (discussion_id, "subject"),
            (repo_id, "context"),
            (author_id, "actor") if author_id else None,
        ]
    )

    # Event: DiscussionAnswered (Q&A category only)
    if discussion.get("answerChosenAt"):
        ts_answered = safe_timestamp(discussion["answerChosenAt"])
        answerer_login = (discussion.get("answerChosenBy") or {}).get("login")
        answerer_id = ensure_user(builder, repo_id, answerer_login, timestamp=ts_answered) if answerer_login else None

        create_event(
            builder=builder,
            event_type=Activities.DISCUSSION_ANSWERED,
            ts=ts_answered,
            attributes={"source": "graphql"},
            relationships=[
                (discussion_id, "subject"),
                (repo_id, "context"),
                (answerer_id, "actor") if answerer_id else None,
            ]
        )

    return discussion_id