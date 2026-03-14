"""
Unified Comment mapper.

All comment types (Issue, PR, Review, Discussion) become Comment objects
with a `comment_type` attribute. A single `CommentCreated` event is generated
once per comment, from its primary source. Secondary sources (e.g. PR_THREADS_QUERY
for ReviewComments) only enrich the existing object — no duplicate events.

Phase responsibilities:
  Phase 2  → IssueComment, PRComment          (primary source)
  Phase 3  → ReviewComment from PR_REVIEWS     (primary source, with_review_comments)
  Phase 3  → ReviewComment from PR_THREADS     (enrichment only, no event)
  Phase 7  → DiscussionComment                 (primary source)
"""

from typing import Dict, Any, Optional
from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user, ensure_file, ensure_comment
from github2ocel.transform.utils.activity import Activities
from shared.ocel.model.models import ObjectInstance
from shared.logger import get_logger

logger = get_logger(__name__)


# Issue Comment
def map_issue_comment(
    comment: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
    issue_id: str,
) -> Optional[str]:
    """
    Primary source for IssueComment objects.
    Called from Phase 2 (fetch_issue_comments → process_issue_comment).
    """
    cid = comment.get("id")
    if not cid:
        return None

    ts = safe_timestamp(comment.get("createdAt"))
    edited_at = safe_timestamp(comment.get("lastEditedAt")) if comment.get("lastEditedAt") else None
    author_login = (comment.get("author") or {}).get("login")
    author_id = ensure_user(builder, repo_id, author_login, timestamp=ts) if author_login else None
    body_text = comment.get("bodyText") or ""

    rels = [
        (issue_id, "comment_of"),
        (repo_id,  "in_repo"),
    ]
    if author_id:
        rels.append((author_id, "authored_by"))

    comment_id = ensure_comment(
        builder=builder,
        repo_id=repo_id,
        comment_id=cid,
        comment_type="issue",
        created_at=comment.get("createdAt", ""),
        attributes={
            "body_length":     len(body_text),
            "reactions_count": (comment.get("reactions") or {}).get("totalCount", 0),
            "is_edited":       1 if edited_at else 0,
            "edited_at":       edited_at,
        },
        relationships=rels,
    )

    if comment_id:
        create_event(
            builder=builder,
            event_type=Activities.COMMENT_CREATED,
            ts=ts,
            attributes={"comment_type": "issue"},
            relationships=[
                (comment_id, "subject"),
                (issue_id,   "context"),
                (author_id,  "actor") if author_id else None,
            ]
        )

    return comment_id


# PR Comment
def map_pr_comment(
    comment: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
    pr_id: str,
) -> Optional[str]:
    """
    Primary source for PRComment objects.
    Called from Phase 2 (fetch_pr_comments → process_pr_comment).
    """
    cid = comment.get("id")
    if not cid:
        return None

    ts = safe_timestamp(comment.get("createdAt"))
    edited_at = safe_timestamp(comment.get("lastEditedAt")) if comment.get("lastEditedAt") else None
    author_login = (comment.get("author") or {}).get("login")
    author_id = ensure_user(builder, repo_id, author_login, timestamp=ts) if author_login else None
    body_text = comment.get("bodyText") or ""

    rels = [
        (pr_id,   "comment_of"),
        (repo_id, "in_repo"),
    ]
    if author_id:
        rels.append((author_id, "authored_by"))

    comment_id = ensure_comment(
        builder=builder,
        repo_id=repo_id,
        comment_id=cid,
        comment_type="pr",
        created_at=comment.get("createdAt", ""),
        attributes={
            "body_length":     len(body_text),
            "reactions_count": (comment.get("reactions") or {}).get("totalCount", 0),
            "is_edited":       1 if edited_at else 0,
            "edited_at":       edited_at,
        },
        relationships=rels,
    )

    if comment_id:
        create_event(
            builder=builder,
            event_type=Activities.COMMENT_CREATED,
            ts=ts,
            attributes={"comment_type": "pr"},
            relationships=[
                (comment_id, "subject"),
                (pr_id,      "context"),
                (author_id,  "actor") if author_id else None,
            ]
        )

    return comment_id


# Review Comment (primary source: PR_REVIEWS_QUERY)
def map_review_comment(
    comment: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
    review_id: str,
    pr_id: str,
) -> Optional[str]:
    """
    Primary source for ReviewComment objects.
    Called from Phase 3 (PR_REVIEWS_QUERY → _map_review_comment in process_review).
    Generates CommentCreated event.
    """
    cid = comment.get("id")
    if not cid:
        return None

    ts = safe_timestamp(comment.get("createdAt"))
    updated_at = comment.get("updatedAt")  # alias for lastEditedAt in query
    author_login = (comment.get("author") or {}).get("login")
    author_id = ensure_user(builder, repo_id, author_login, timestamp=ts) if author_login else None
    body_text = comment.get("bodyText") or ""
    path = comment.get("path") or ""
    diff_hunk = (comment.get("diffHunk") or "")[:500]

    rels = [
        (review_id, "belongs_to_review"),
        (pr_id,     "comment_of"),
        (repo_id,   "in_repo"),
    ]
    if author_id:
        rels.append((author_id, "authored_by"))

    # Comment → File O2O (ensure_file creates stub if Phase 4b hasn't run yet)
    file_id = None
    if path:
        file_id = ensure_file(builder, repo_id, path, timestamp=ts)
        if file_id:
            rels.append((file_id, "on_file"))

    comment_id = ensure_comment(
        builder=builder,
        repo_id=repo_id,
        comment_id=cid,
        comment_type="review",
        created_at=comment.get("createdAt", ""),
        attributes={
            "body_length":     len(body_text),
            "reactions_count": (comment.get("reactions") or {}).get("totalCount", 0),
            "is_edited":       1 if (updated_at and updated_at != comment.get("createdAt")) else 0,
            "path":            path,
            "line":            comment.get("line") or 0,
            "position":        comment.get("position") or 0,
            "diff_hunk":       diff_hunk,
        },
        relationships=rels,
    )

    if comment_id:
        create_event(
            builder=builder,
            event_type=Activities.COMMENT_CREATED,
            ts=ts,
            attributes={
                "comment_type": "review",
                "path":         path,
            },
            relationships=[
                (comment_id, "subject"),
                (review_id,  "review_context"),
                (pr_id,      "context"),
                (author_id,  "actor")   if author_id else None,
                (file_id,    "on_file") if file_id  else None,
            ]
        )

    return comment_id


# Review Comment enrichment (secondary source: PR_THREADS_QUERY)
def enrich_review_comment_from_thread(
    comment: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
    pr_id: str,
    thread_id: str,
    reply_to_id: Optional[str] = None,
) -> Optional[str]:
    """
    Enrichment-only — NO event generated.
    Called from Phase 3 (PR_THREADS_QUERY → process_review_thread).
    Adds thread context, replyTo O2O, and original_line/outdated attributes
    that are not available in PR_REVIEWS_QUERY.
    """
    cid = comment.get("id")
    if not cid:
        return None

    comment_id = make_id(repo_id, "comment", cid)
    author_login = (comment.get("author") or {}).get("login")
    ts = safe_timestamp(comment.get("createdAt"))
    author_id = ensure_user(builder, repo_id, author_login, timestamp=ts) if author_login else None

    rels = [(pr_id, "comment_of")]
    if author_id:
        rels.append((author_id, "authored_by"))

    # Comment → Comment (replies_to) — thread conversation structure
    if reply_to_id:
        reply_obj_id = make_id(repo_id, "comment", reply_to_id)
        if builder.object_exists(reply_obj_id):
            rels.append((reply_obj_id, "replies_to"))

    # Enrich with thread-specific fields (allow_update=True in ensure_comment)
    return ensure_comment(
        builder=builder,
        repo_id=repo_id,
        comment_id=cid,
        comment_type="review",
        created_at=comment.get("createdAt", ""),
        attributes={
            "original_line": comment.get("originalLine") or 0,
            "is_outdated":   1 if comment.get("outdated") else 0,
            "thread_id":     thread_id,
        },
        relationships=rels,
    )


# Discussion Comment
def map_discussion_comment(
    comment: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
    discussion_id: str,
    parent_comment_id: Optional[str] = None,
) -> Optional[str]:
    """
    Primary source for DiscussionComment objects.
    Called from Phase 7 (DISCUSSIONS_QUERY → process_discussion_node).
    Also handles replies (parent_comment_id set for nested replies).
    """
    cid = comment.get("id")
    if not cid:
        return None

    ts = safe_timestamp(comment.get("createdAt"))
    author_login = (comment.get("author") or {}).get("login")
    author_id = ensure_user(builder, repo_id, author_login, timestamp=ts) if author_login else None
    body_text = comment.get("bodyText") or ""

    rels = [
        (discussion_id, "comment_of"),
        (repo_id,       "in_repo"),
    ]
    if author_id:
        rels.append((author_id, "authored_by"))

    # Comment → Comment (replies_to) for discussion threading
    if parent_comment_id:
        parent_obj_id = make_id(repo_id, "comment", parent_comment_id)
        if builder.object_exists(parent_obj_id):
            rels.append((parent_obj_id, "replies_to"))

    comment_id = ensure_comment(
        builder=builder,
        repo_id=repo_id,
        comment_id=cid,
        comment_type="discussion",
        created_at=comment.get("createdAt", ""),
        attributes={
            "body_length":     len(body_text),
            "reactions_count": (comment.get("reactions") or {}).get("totalCount", 0),
            "is_answer":       1 if comment.get("isAnswer") else 0,
        },
        relationships=rels,
    )

    if comment_id:
        create_event(
            builder=builder,
            event_type=Activities.COMMENT_CREATED,
            ts=ts,
            attributes={
                "comment_type": "discussion",
                "is_answer":    1 if comment.get("isAnswer") else 0,
            },
            relationships=[
                (comment_id,    "subject"),
                (discussion_id, "context"),
                (author_id,     "actor") if author_id else None,
            ]
        )

    return comment_id