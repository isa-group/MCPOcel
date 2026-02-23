import logging
from typing import Dict, Any
import uuid

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.helper import safe_timestamp
from github2ocel.transform.utils.ensure import make_id, ensure_user
from github2ocel.transform.utils.activity import Activities
from shared.ocel.model.models  import Event, ObjectInstance

def process_discussion_comment(
    comment: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
    discussion_id: str
) -> None:
    comment_id = make_id(discussion_id, "comment", comment["id"])

    ts_created = safe_timestamp(comment.get("createdAt"))

    # Object
    comment_obj = ObjectInstance(
        object_id=comment_id,
        object_type="DiscussionComment"
    )

    comment_obj.add_snapshot(
        time=ts_created,
        attributes={
            "body_length": len(comment.get("bodyText", "") or ""),
            "reactions_count": (comment.get("reactions") or {}).get("totalCount", 0),
        }
    )

    comment_obj.add_rel(discussion_id, "comment_of_discussion")

    builder.insert_object(comment_obj)

    # Event
    evt = Event(
        event_id=str(uuid.uuid4()),
        event_type=Activities.DISCUSSION_COMMENT_CREATED,
        time=ts_created,
        attributes={}
    )

    author_login = (comment.get("author") or {}).get("login")
    if author_login:
        user_id = ensure_user(builder, repo_id, author_login)
        evt.add_rel(user_id, "actor")

    evt.add_rel(comment_id, "created_comment")
    evt.add_rel(discussion_id, "subject")
    evt.add_rel(repo_id, "context")

    builder.insert_event(evt)
