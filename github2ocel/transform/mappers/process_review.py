
from typing import Dict, Any
from shared.ocel.builder import OCELBuilder
from shared.ocel.model.models import ObjectInstance
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user
from github2ocel.transform.utils.activity import Activities
from shared.logger import get_logger

logger = get_logger(__name__)

_REVIEW_STATE_TO_ACTIVITY = {
    "APPROVED":           Activities.PR_REVIEW_APPROVED,
    "CHANGES_REQUESTED":  Activities.PR_REVIEW_CHANGES_REQUESTED,
    "COMMENTED":          Activities.PR_REVIEW_COMMENTED,
    "DISMISSED":          Activities.PR_REVIEW_DISMISSED,
}


def process_review(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    review_id_raw = node.get("id")
    pr_number     = node.get("__pr_number")

    if not review_id_raw or not pr_number:
        logger.warning("[process_review] Missing id or __pr_number. Skipping.")
        return

    pr_id      = make_id(repo_id, "pr", pr_number)
    review_id  = make_id(repo_id, "review", review_id_raw)
    state      = node.get("state", "COMMENTED")
    submitted  = safe_timestamp(node.get("submittedAt"))

    author_login = (node.get("author") or {}).get("login")
    author_id = ensure_user(builder, repo_id, author_login, timestamp=submitted) if author_login else None

    # Object: Review
    obj = ObjectInstance(object_id=review_id, object_type="Review")
    obj.add_snapshot(
        time=submitted,
        attributes={
            "state":        state,
            "body_length":  len(node.get("body") or ""),
            "comments_count": (node.get("comments") or {}).get("totalCount", 0),
            "submitted_at": submitted,
        }
    )

    # O2O: Review -> PR
    if builder.object_exists(pr_id):
        obj.add_rel(pr_id, "belongs_to_pr")

    # O2O: Review -> Reviewer
    if author_id:
        obj.add_rel(author_id, "submitted_by")

    builder.insert_object(obj)

    # Event: Review submitted
    activity = _REVIEW_STATE_TO_ACTIVITY.get(state, Activities.PR_REVIEW_COMMENTED)

    create_event(
        builder=builder,
        event_type=activity,
        ts=submitted,
        attributes={
            "review_state": state,
            "body_length": len(node.get("body") or ""),
            "source": "graphql",
        },
        relationships=[
            (review_id, "subject"),
            (pr_id, "context"),
            (author_id, "reviewer") if author_id else None,
            (repo_id, "repository"),
        ]
    )

    # Events: ReviewCommentCreated (inline code comments)
    for comment in (node.get("comments") or {}).get("nodes", []):
        _map_review_comment(comment, builder, repo_id, review_id, pr_id)


def _map_review_comment(
    comment: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
    review_id: str,
    pr_id: str,
) -> None:
    if not comment.get("id"):
        return

    ts = safe_timestamp(comment.get("createdAt"))
    author_login = (comment.get("author") or {}).get("login")
    author_id = ensure_user(builder, repo_id, author_login, timestamp=ts) if author_login else None

    create_event(
        builder=builder,
        event_type=Activities.REVIEW_COMMENT_CREATED,
        ts=ts,
        attributes={
            "comment_id": comment["id"],
            "path": comment.get("path", ""),
            "line": comment.get("line") or 0,
            "body_length": len(comment.get("body") or ""),
            "reactions_count": (comment.get("reactions") or {}).get("totalCount", 0),
            "is_edited": 1 if comment.get("updatedAt") != comment.get("createdAt") else 0,
        },
        relationships=[
            (review_id, "belongs_to_review"),
            (pr_id, "context"),
            (author_id, "actor") if author_id else None,
        ]
    )
