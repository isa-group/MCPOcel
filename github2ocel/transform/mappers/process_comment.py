"""
Unified Comment mapper.

All comment types (Issue, PR, Review, Discussion) become Comment objects
with a `comment_type` attribute. Events use COMMENT_CREATED / COMMENT_EDITED
for all types — comment_type, author_association, and is_bot attributes
allow filtering in process mining without joins.

Phase responsibilities:
  Phase 2  → IssueComment, PRComment          (primary source)
  Phase 3  → ReviewComment from PR_REVIEWS     (primary source, with_review_comments)
  Phase 3  → ReviewComment from PR_THREADS     (enrichment only, no event)
  Phase 7  → DiscussionComment                 (primary source, embedded)
  Phase 7b → DiscussionComment                 (overflow pagination)
"""

from typing import Dict, Any, Optional

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user, ensure_file, ensure_comment
from github2ocel.transform.utils.activity import Activities
from shared.logger import get_logger

logger = get_logger(__name__)


def _extract_author(comment: Dict[str, Any], builder, repo_id: str, ts: str):
    """Extract author identity and bot flag from a comment node."""
    author_node       = comment.get("author") or {}
    author_login      = author_node.get("login")
    author_typename   = author_node.get("__typename", "User")
    is_bot            = 1 if author_typename == "Bot" else 0
    author_id         = ensure_user(builder, repo_id, author_login, timestamp=ts) if author_login else None
    return author_id, is_bot


def _comment_meta(comment: Dict[str, Any]) -> Dict[str, Any]:
    """Extract fields common to all comment types."""
    body_text          = comment.get("bodyText") or ""
    edited_at_raw      = comment.get("lastEditedAt")
    edited_at          = safe_timestamp(edited_at_raw) if edited_at_raw else None
    is_edited          = 1 if edited_at else 0
    author_association = comment.get("authorAssociation", "")
    is_minimized       = 1 if comment.get("isMinimized") else 0
    minimized_reason   = comment.get("minimizedReason") or ""
    url                = comment.get("url", "")
    reactions_count    = (comment.get("reactions") or {}).get("totalCount", 0)
    return {
        "body_length":        len(body_text),
        "reactions_count":    reactions_count,
        "is_edited":          is_edited,
        "edited_at":          edited_at,
        "author_association": author_association,
        "is_minimized":       is_minimized,
        "minimized_reason":   minimized_reason,
        "url":                url,
    }


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
    author_id, is_bot = _extract_author(comment, builder, repo_id, ts)
    meta = _comment_meta(comment)

    rels = [(issue_id, "comment_of"), (repo_id, "in_repo")]
    if author_id:
        rels.append((author_id, "authored_by"))

    comment_id = ensure_comment(
        builder=builder,
        repo_id=repo_id,
        comment_id=cid,
        comment_type="issue",
        created_at=comment.get("createdAt", ""),
        attributes={**meta, "is_bot": is_bot},
        relationships=rels,
    )

    if comment_id:
        event_rels = [
            (comment_id, "subject"),
            (issue_id,   "context"),
            (author_id,  "actor") if author_id else None,
        ]
        create_event(
            builder=builder,
            event_type=Activities.COMMENT_CREATED,
            ts=ts,
            attributes={
                "comment_type":       "issue",
                "author_association": meta["author_association"],
                "is_bot":             is_bot,
            },
            relationships=event_rels,
        )
        if meta["edited_at"] and meta["edited_at"] != ts:
            create_event(
                builder=builder,
                event_type=Activities.COMMENT_EDITED,
                ts=meta["edited_at"],
                attributes={"comment_type": "issue"},
                relationships=[(comment_id, "subject"), (issue_id, "context")],
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
    author_id, is_bot = _extract_author(comment, builder, repo_id, ts)
    meta = _comment_meta(comment)

    rels = [(pr_id, "comment_of"), (repo_id, "in_repo")]
    if author_id:
        rels.append((author_id, "authored_by"))

    comment_id = ensure_comment(
        builder=builder,
        repo_id=repo_id,
        comment_id=cid,
        comment_type="pr",
        created_at=comment.get("createdAt", ""),
        attributes={**meta, "is_bot": is_bot},
        relationships=rels,
    )

    if comment_id:
        event_rels = [
            (comment_id, "subject"),
            (pr_id,      "context"),
            (author_id,  "actor") if author_id else None,
        ]
        create_event(
            builder=builder,
            event_type=Activities.COMMENT_CREATED,
            ts=ts,
            attributes={
                "comment_type":       "pr",
                "author_association": meta["author_association"],
                "is_bot":             is_bot,
            },
            relationships=event_rels,
        )
        if meta["edited_at"] and meta["edited_at"] != ts:
            create_event(
                builder=builder,
                event_type=Activities.COMMENT_EDITED,
                ts=meta["edited_at"],
                attributes={"comment_type": "pr"},
                relationships=[(comment_id, "subject"), (pr_id, "context")],
            )

    return comment_id


# Review Comment (primary: PR_REVIEWS_QUERY)
def map_review_comment(
    comment: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
    review_id: str,
    pr_id: str,
) -> Optional[str]:
    """
    Primary source for ReviewComment objects.
    Called from Phase 3 (PR_REVIEWS_QUERY → process_review).
    Generates COMMENT_CREATED (and COMMENT_EDITED when applicable).
    """
    cid = comment.get("id")
    if not cid:
        return None

    ts = safe_timestamp(comment.get("createdAt"))
    author_id, is_bot = _extract_author(comment, builder, repo_id, ts)
    body_text = comment.get("bodyText") or ""
    path = comment.get("path") or ""
    diff_hunk = (comment.get("diffHunk") or "")[:500]

    updated_at_raw = comment.get("updatedAt")
    is_edited = 1 if (updated_at_raw and updated_at_raw != comment.get("createdAt")) else 0
    edited_at = safe_timestamp(updated_at_raw) if is_edited else None

    rels = [
        (review_id, "belongs_to_review"),
        (pr_id,     "comment_of"),
        (repo_id,   "in_repo"),
    ]
    if author_id:
        rels.append((author_id, "authored_by"))

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
            "is_edited":       is_edited,
            "edited_at":       edited_at,
            "is_bot":          is_bot,
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
                "is_bot":       is_bot,
            },
            relationships=[
                (comment_id, "subject"),
                (review_id,  "review_context"),
                (pr_id,      "context"),
                (author_id,  "actor")   if author_id else None,
                (file_id,    "on_file") if file_id   else None,
            ]
        )
        if edited_at:
            create_event(
                builder=builder,
                event_type=Activities.COMMENT_EDITED,
                ts=edited_at,
                attributes={"comment_type": "review", "path": path},
                relationships=[
                    (comment_id, "subject"),
                    (review_id,  "review_context"),
                    (pr_id,      "context"),
                    (file_id,    "on_file") if file_id else None,
                ]
            )

    return comment_id


# Review Comment enrichment (secondary: PR_THREADS_QUERY)
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
    Adds thread_id, replyTo O2O, original_line, and is_outdated — fields
    not available in PR_REVIEWS_QUERY.
    """
    cid = comment.get("id")
    if not cid:
        return None

    ts = safe_timestamp(comment.get("createdAt"))
    author_id, _ = _extract_author(comment, builder, repo_id, ts)

    rels = [(pr_id, "comment_of")]
    if author_id:
        rels.append((author_id, "authored_by"))
    if reply_to_id:
        reply_obj_id = make_id(repo_id, "comment", reply_to_id)
        if builder.object_exists(reply_obj_id):
            rels.append((reply_obj_id, "replies_to"))

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

    Called from:
      - Phase 7: embedded comments in DISCUSSIONS_QUERY
      - Phase 7b: overflow pagination via fetch_discussion_comments

    Replies are passed with parent_comment_id set to the parent comment's
    GitHub node ID, which creates a replies_to O2O for threading.
    """
    cid = comment.get("id")
    if not cid:
        return None

    ts = safe_timestamp(comment.get("createdAt"))
    author_id, is_bot = _extract_author(comment, builder, repo_id, ts)
    meta = _comment_meta(comment)
    is_answer = 1 if comment.get("isAnswer") else 0

    rels = [(discussion_id, "comment_of"), (repo_id, "in_repo")]
    if author_id:
        rels.append((author_id, "authored_by"))
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
            **meta,
            "is_bot":    is_bot,
            "is_answer": is_answer,
        },
        relationships=rels,
    )

    if comment_id:
        create_event(
            builder=builder,
            event_type=Activities.COMMENT_CREATED,
            ts=ts,
            attributes={
                "comment_type":       "discussion",
                "author_association": meta["author_association"],
                "is_bot":             is_bot,
                "is_answer":          is_answer,
            },
            relationships=[
                (comment_id,    "subject"),
                (discussion_id, "context"),
                (author_id,     "actor") if author_id else None,
            ]
        )
        if meta["edited_at"] and meta["edited_at"] != ts:
            create_event(
                builder=builder,
                event_type=Activities.COMMENT_EDITED,
                ts=meta["edited_at"],
                attributes={"comment_type": "discussion"},
                relationships=[(comment_id, "subject"), (discussion_id, "context")],
            )

    return comment_id