from typing import Dict, Any
from shared.ocel.builder import OCELBuilder
from shared.ocel.model.models import ObjectInstance
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.mappers.process_comment import map_review_comment, enrich_review_comment_from_thread
from shared.logger import get_logger

logger = get_logger(__name__)

_REVIEW_STATE_TO_ACTIVITY = {
    "APPROVED":           Activities.PR_REVIEW_APPROVED,
    "CHANGES_REQUESTED":  Activities.PR_REVIEW_CHANGES_REQUESTED,
    "COMMENTED":          Activities.PR_REVIEW_COMMENTED,
    "DISMISSED":          Activities.PR_REVIEW_DISMISSED,
}


def process_review(
    node: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
    with_review_comments: bool = True,
) -> None:
    """
    Process a PR review node from PR_REVIEWS_QUERY.

    Args:
        with_review_comments: map inline ReviewComment events (controlled by profile flag)

    Note: review threads are handled separately by process_review_thread(),
    called from fetch_pr_threads (Phase 3) when withThreads=True.
    """
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

    body_text = node.get("bodyText") or ""

    # Object: Review
    obj = ObjectInstance(object_id=review_id, object_type="Review")
    obj.add_snapshot(
        time=submitted,
        attributes={
            "state":          state,
            "body_length":    len(body_text),
            "comments_count": (node.get("comments") or {}).get("totalCount", 0),
            "submitted_at":   submitted,
        }
    )

    # O2O: Review -> PR
    if builder.object_exists(pr_id):
        obj.add_rel(pr_id, "belongs_to_pr")

    # O2O: Review -> Reviewer
    if author_id:
        obj.add_rel(author_id, "submitted_by")

    builder.insert_object(obj)

    # Event: review submitted
    activity = _REVIEW_STATE_TO_ACTIVITY.get(state, Activities.PR_REVIEW_COMMENTED)

    create_event(
        builder=builder,
        event_type=activity,
        ts=submitted,
        attributes={
            "review_state": state,
            "body_length":  len(body_text),
            "source":       "graphql",
        },
        relationships=[
            (review_id, "subject"),
            (pr_id,     "context"),
            (author_id, "reviewer") if author_id else None,
            (repo_id,   "repository"),
        ]
    )

    # Events: ReviewCommentCreated (inline code comments)
    # Only processed when withReviewComments=True (STANDARD/COMPLETE profile)
    if with_review_comments:
        for comment in (node.get("comments") or {}).get("nodes", []):
            map_review_comment(comment, builder, repo_id, review_id, pr_id)





def process_review_thread(
    thread: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
) -> None:
    """
    Map a review thread node to a ThreadResolved event.

    Called from Phase 3 (fetch_pr_threads) when withThreads=True (COMPLETE profile).
    The thread dict must have '__pr_number' injected by the fetcher.
    Only resolved threads generate an event — unresolved threads have no completion.
    """
    if not thread.get("id"):
        return

    if not thread.get("isResolved"):
        return

    pr_number = thread.get("__pr_number")
    if not pr_number:
        return

    pr_id = make_id(repo_id, "pr", pr_number)
    if not builder.object_exists(pr_id):
        return

    resolver_login = (thread.get("resolvedBy") or {}).get("login")

    # Use first comment's timestamp as proxy — threads have no own timestamp
    first_comment = ((thread.get("comments") or {}).get("nodes") or [None])[0]
    ts_raw = (first_comment or {}).get("createdAt") if first_comment else None
    ts = safe_timestamp(ts_raw) if ts_raw else safe_timestamp("1970-01-01T00:00:00Z")

    resolver_id = ensure_user(builder, repo_id, resolver_login, timestamp=ts) if resolver_login else None

    thread_comments = (thread.get("comments") or {}).get("nodes") or []
    first_path = (first_comment or {}).get("path", "") if first_comment else ""

    # Enrich each thread comment with replyTo O2O and thread-specific fields
    # No CommentCreated event — already generated from PR_REVIEWS_QUERY
    prev_id = None
    for tc in thread_comments:
        if not tc:
            continue
        reply_to = (tc.get("replyTo") or {}).get("id")
        enrich_review_comment_from_thread(
            comment=tc,
            builder=builder,
            repo_id=repo_id,
            pr_id=pr_id,
            thread_id=thread["id"],
            reply_to_id=reply_to,
        )
        prev_id = tc.get("id")

    create_event(
        builder=builder,
        event_type=Activities.THREAD_RESOLVED,
        ts=ts,
        attributes={
            "thread_id":      thread["id"],
            "is_outdated":    int(thread.get("isOutdated", False)),
            "comments_count": len(thread_comments),
            "path":           first_path,
            "source":         "graphql",
        },
        relationships=[
            (pr_id,       "context"),
            (resolver_id, "resolved_by") if resolver_id else None,
        ]
    )