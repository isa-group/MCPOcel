import logging
from typing import Dict, Any
from github2ocel.transform.builder import OCELBuilder
from github2ocel.transform.utils.helper import safe_timestamp
from github2ocel.transform.utils.ensure import (
    ensure_comment,
    ensure_user,
    ensure_label,
    ensure_file,
    ensure_review_comment,
    is_pull_request
)
from github2ocel.transform.utils.activity import Activities

logger = logging.getLogger(__name__)

def map_lifecycle_events(node: Dict[str, Any], builder: OCELBuilder,
                         repo_id: str, target_id: str) -> None:
    """
    Lifecycle event orchestrator.
    Divides processing into tags, comments, and revisions.
    """
    _map_labels(node, builder, repo_id, target_id)
    _map_comments(node, builder, repo_id, target_id)

    # Reviews are exclusive to Pull Requests.
    if is_pull_request(node):
        _map_reviews(node, builder, repo_id, target_id)


def _map_labels(node: Dict[str, Any], builder: OCELBuilder,
                repo_id: str, target_id: str) -> None:
    """Process the addition of labels as events.."""
    for lbl in node.get("labels", {}).get("nodes", []):
        if not lbl: continue

        label_id = ensure_label(builder, repo_id, lbl)
        if not label_id: continue

        # Metadata for inferred events
        state_meta = {
            "event_class": "state_derived",
            "source": "labels_snapshot",
            "confidence": "medium",
            "note": "Timestamp is inferred from the parent node state"
        }

        try:
            # We try to obtain a realistic date of when the label was added
            ts = safe_timestamp(
                lbl.get("createdAt"),
                fallback=node.get("updatedAt") or node.get("createdAt"),
                use_now=True
            )
            builder.add_object_relationship(target_id, label_id, "has_label")
            builder.add_event(
                Activities.LABEL_ADDED,
                ts,
                [builder.rel(target_id, "target"), builder.rel(label_id, "label")],
                state_meta
            )
        except Exception as e:
            logger.warning(f"Error mapping tag in {target_id}: {e}")


def _map_comments(node: Dict[str, Any], builder: OCELBuilder,
                  repo_id: str, target_id: str) -> None:
    """Process standard comments from Issues/PRs."""
    obs_meta = {
        "event_class": "observed",
        "source": "github_graphql_comments",
        "confidence": "high"
    }

    for comment in node.get("comments", {}).get("nodes", []):
        if not comment or not comment.get("createdAt"):
            continue

        comment_id = ensure_comment(builder, repo_id, comment)
        author_id = ensure_user(builder, comment.get("author", {}).get("login"))

        rels = [builder.rel(comment_id, "comment"), builder.rel(target_id, "parent")]
        if author_id:
            rels.append(builder.rel(author_id, "author"))

        try:
            # Create Event
            builder.add_event(
                Activities.COMMENT_CREATED, comment["createdAt"],
                rels,
                obs_meta
            )

            # Edit event
            last_edited = comment.get("lastEditedAt")
            if last_edited and last_edited != comment["createdAt"]:
                builder.add_event(
                    Activities.
                    COMMENT_EDITED,
                     last_edited,
                      rels,
                      obs_meta
                )
        except Exception as e:
            logger.warning(f"Error in comment event {comment_id}: {e}")


def _map_reviews(node: Dict[str, Any], builder: OCELBuilder,
                 repo_id: str, target_id: str) -> None:
    """Processes code reviews and their statuses."""
    activity_map = {
        "APPROVED": Activities.PR_REVIEW_APPROVED,
        "CHANGES_REQUESTED": Activities.PR_REVIEW_CHANGES_REQUESTED,
        "COMMENTED": Activities.PR_REVIEW_COMMENTED,
        "DISMISSED": Activities.PR_REVIEW_DISMISSED
    }

    obs_meta = {
        "event_class": "observed",
        "source": "github_reviews",
        "confidence": "high"
    }

    for review in node.get("reviews", {}).get("nodes", []):
        if not review or not review.get("submittedAt"):
            continue

        reviewer_id = ensure_user(builder, review.get("author", {}).get("login"))
        state = review.get("state", "COMMENTED")
        activity = activity_map.get(state, Activities.PR_REVIEW)

        rels = [builder.rel(target_id, "target")]
        if reviewer_id:
            rels.append(builder.rel(reviewer_id, "reviewer"))

        try:
            builder.add_event(
                activity,
                review["submittedAt"],
                rels,
                {**obs_meta, "review_state": state}
            )

            _map_review_line_comments(review, builder, repo_id, target_id)
        except Exception as e:
            logger.warning(f"Error in PR review {target_id}: {e}")


def _map_review_line_comments(review: Dict[str, Any], builder: OCELBuilder,
                             repo_id: str, pr_id: str) -> None:
    """Process specific comments on lines of code within a revision."""
    obs_meta = {
        "event_class": "observed",
        "source": "github_review_line_comments",
        "confidence": "high"
    }

    for comment in review.get("comments", {}).get("nodes", []):
        if not comment or not comment.get("createdAt"):
            continue

        comment_id = ensure_review_comment(builder, repo_id, comment)
        author_id = ensure_user(builder, comment.get("author", {}).get("login"))

        file_id = None
        if comment.get("path"):
            file_id = ensure_file(builder, repo_id, comment["path"])

        rels = [builder.rel(comment_id, "comment"), builder.rel(pr_id, "pull_request")]
        if author_id: rels.append(builder.rel(author_id, "author"))
        if file_id: rels.append(builder.rel(file_id, "file"))

        try:
            builder.add_event(
                Activities.REVIEW_COMMENT_CREATED,
                comment["createdAt"],
                rels,
                {**obs_meta, "path": comment.get("path", "")}
            )
        except Exception as e:
            logger.debug(f"Error in review line comment: {e}")

def _map_review_threads(node: Dict[str, Any], builder: OCELBuilder, pr_id: str) -> None:
    """Mapea hilos de conversación y su resolución."""
    threads = node.get("reviewThreads", {}).get("nodes", [])

    for thread in threads:
        thread_id = thread["id"]
        builder.add_object(thread_id, "ReviewThread", {"is_resolved": thread["isResolved"]})
        builder.add_object_relationship(pr_id, thread_id, "contains_thread")

        # Si está resuelto, generamos un evento de resolución
        if thread["isResolved"] and thread.get("resolvedBy"):
            res_author = ensure_user(builder, thread["resolvedBy"]["login"])
            builder.add_event(
                "ReviewThreadResolved",
                # Nota: GraphQL no da el timestamp exacto de resolución fácilmente sin el timeline
                node.get("updatedAt"), 
                [builder.rel(thread_id, "thread"), builder.rel(res_author, "resolver")],
                {"event_class": "state_derived", "confidence": "medium"}
            )