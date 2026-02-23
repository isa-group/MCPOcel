import logging
import uuid
from typing import Dict, Any

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.utils.helper import safe_timestamp
from github2ocel.transform.utils.ensure import make_id, ensure_user
from shared.ocel.model.models  import Event, ObjectInstance

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
            "number": discussion_number,
            "title": discussion.get("title"),
            "url": discussion.get("url"),
            "locked": int(discussion.get("locked", False)),
            "category": discussion.get("category", {}).get("name"),
            "reactions_count": discussion.get("reactions", {}).get("totalCount", 0),
        }
    )

    discussion_obj.add_rel(repo_id, "discussion_of_repo")

    builder.insert_object(discussion_obj)

    # Created Event    
    evt = Event(
        event_id=str(uuid.uuid4()),
        event_type=Activities.DISCUSSION_CREATED,
        time=ts_created,
        attributes={}
    )
    author_login = (discussion.get("author") or {}).get("login")
    if author_login:
        user_id = ensure_user(builder, repo_id, author_login)
        evt.add_rel(user_id, "actor")

    evt.add_rel(discussion_id, "created_discussion")
    evt.add_rel(repo_id, "context")

    builder.insert_event(evt)

    # Answered Event (Q&A only)
    if discussion.get("answerChosenAt"):
        evt_answered = Event(
            event_id=str(uuid.uuid4()),
            event_type=Activities.DISCUSSION_ANSWERED,
            time=safe_timestamp(discussion["answerChosenAt"]),
            attributes={}
        )

        evt_answered.add_rel(discussion_id, "answered_discussion")
        evt_answered.add_rel(repo_id, "context")

        builder.insert_event(evt_answered)

    return discussion_id
