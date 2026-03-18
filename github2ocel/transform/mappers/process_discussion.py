from typing import Dict, Any

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user, ensure_label
from shared.ocel.model.models  import ObjectInstance

def process_discussion(
    discussion: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str
) -> str:
    """
    Registers a GitHub Discussion as an OCEL object + creation event.
    """
    discussion_number = discussion.get("number")
    if discussion_number is None:
        return None

    discussion_id = make_id(repo_id, "discussion", discussion_number)

    ts_created = safe_timestamp(discussion.get("createdAt"))

    # Object
    discussion_obj = ObjectInstance(
        object_id=discussion_id,
        object_type="Discussion"
    )

    discussion_obj.add_snapshot(
        time=ts_created,
        attributes={
            "number":          discussion_number,
            "title":           discussion.get("title"),
            "url":             discussion.get("url"),
            "locked":          int(discussion.get("locked", False)),
            "category":        (discussion.get("category") or {}).get("name", ""),
            "body_length":     len(discussion.get("bodyText") or ""),
            "upvote_count":    discussion.get("upvoteCount") or 0,
            "reactions_count":  (discussion.get("reactions") or {}).get("totalCount", 0),
            "comments_total":   (discussion.get("comments") or {}).get("totalCount", 0),
        }
    )

    discussion_obj.add_rel(repo_id, "discussion_of_repo")

    author_login = (discussion.get("author") or {}).get("login")
    user_id = None
    if author_login:
        user_id = ensure_user(builder, repo_id, author_login, timestamp=ts_created)
        discussion_obj.add_rel(target_id=user_id, qualifier="created_by")

    # O2O → Labels
    for lbl in (discussion.get("labels") or {}).get("nodes") or []:
        if lbl and lbl.get("id"):
            lbl_id = ensure_label(builder, repo_id, lbl, timestamp=ts_created)
            if lbl_id:
                discussion_obj.add_rel(lbl_id, "has_label")

    builder.insert_object(discussion_obj)

    # Created Event
    create_event(
        builder=builder,
        event_type=Activities.DISCUSSION_CREATED,
        ts=ts_created,
        attributes={},
        relationships=[
            (user_id, "actor") if user_id else None,
            (discussion_id, "created_discussion"),
            (repo_id, "context")
        ]
    )

    # Answered Event (Q&A only)
    if discussion.get("answerChosenAt"):
        ts_answered = safe_timestamp(discussion["answerChosenAt"])
        answerer_login = (discussion.get("answerChosenBy") or {}).get("login")
        answerer_id = ensure_user(builder, repo_id, answerer_login, timestamp=ts_answered)

        create_event(
            builder=builder,
            event_type=Activities.DISCUSSION_ANSWERED,
            ts=ts_answered,
            attributes={},
            relationships=[
                (discussion_id, "answered_discussion"),
                (repo_id, "context"),
                (answerer_id, "actor") if answerer_login else None
            ]
        )

    return discussion_id