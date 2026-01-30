import logging
from typing import Dict, Any

from github2ocel.transform.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, safe_timestamp

from github2ocel.transform.utils.ensure_object import ensure_comment, ensure_user, ensure_label
from github2ocel.transform.utils.activity import Activities

logger = logging.getLogger(__name__)

# Lifecycle Mappers: Labels, Comments, Reviews
def map_lifecycle_events(node: Dict[str, Any], builder: OCELBuilder,
                          repo_id: str, target_id: str) -> None:
    """
    Map lifecycle events (labels, comments, reviews) for issues/PRs.
    Handles missing data gracefully.
    """
    # Labels
    for lbl in node.get("labels", {}).get("nodes", []):
        if not lbl:
            continue

        label_id = ensure_label(builder, repo_id, lbl)
        if not label_id:
            continue

        try:
            ts = safe_timestamp(
                lbl.get("createdAt"),
                fallback=node.get("updatedAt") or node.get("createdAt"),
                use_now=True
            )
            builder.add_object_relationship(target_id, label_id, "has_label")
            builder.add_event(
                Activities.LABEL_ADDED,
                ts,
                [builder.rel(target_id, "target"), builder.rel(label_id, "label")]
            )
        except Exception as e:
            logger.warning(f"Failed to map label event: {e}")

    # Comments
    for comment in node.get("comments", {}).get("nodes", []):
        if not comment or not comment.get("createdAt"):
            continue

        comment_id = ensure_comment(builder, repo_id, comment)
        if not comment_id:
            continue

        author_id = ensure_user(builder, comment.get("author", {}).get("login"))

        rels = [
            builder.rel(comment_id, "comment"),
            builder.rel(target_id, "parent")
        ]
        if author_id:
            rels.append(builder.rel(author_id, "author"))

        try:
            builder.add_event(
                Activities.COMMENT_CREATED,
                comment["createdAt"],
                rels
            )

            # Comment edited
            if (comment.get("lastEditedAt") and
                comment["lastEditedAt"] != comment["createdAt"]):
                builder.add_event(
                    Activities.COMMENT_EDITED,
                    comment["lastEditedAt"],
                    rels
                )
        except Exception as e:
            logger.warning(f"Failed to map comment event: {e}")

    # PR Reviews
    for review in node.get("reviews", {}).get("nodes", []):
        if not review or not review.get("submittedAt"):
            continue

        reviewer_id = ensure_user(builder, review.get("author", {}).get("login"))
        if not reviewer_id:
            continue

        try:
            builder.add_event(
                Activities.PR_REVIEW,
                review["submittedAt"],
                [
                    builder.rel(target_id, "target"),
                    builder.rel(reviewer_id, "reviewer")
                ],
                {"state": review.get("state", "COMMENTED")}
            )
        except Exception as e:
            logger.warning(f"Failed to map review event: {e}")


# Issue & Pull Request Mappers
def process_issue_node(node: Dict[str, Any], builder: OCELBuilder,
                       repo_id: str) -> None:
    """
    Process an issue or PR node from GraphQL.
    Validates required fields before processing.
    """
    # Validate required fields
    if not node.get("number") or not node.get("createdAt"):
        logger.warning(f"Skipping invalid issue/PR node: {node.get('id')}")
        return

    is_pr = node.get("__type") == "PullRequest" or "merged" in node
    obj_type = "PullRequest" if is_pr else "Issue"

    try:
        obj_id = make_id(repo_id, "pr" if is_pr else "issue", node["number"])
    except ValueError as e:
        logger.error(f"Failed to create ID for {obj_type}: {e}")
        return

    # Build attributes
    attrs = {
        "number": node["number"],
        "title": node.get("title", ""),
        "state": node.get("state", "OPEN")
    }

    if is_pr:
        attrs.update({
            "merged": node.get("merged", False),
            "head_ref": node.get("headRefName", ""),
            "base_ref": node.get("baseRefName", "")
        })

    builder.add_object(obj_id, obj_type, attrs)

    # Build relationships
    author_id = ensure_user(builder, node.get("author", {}).get("login"))
    rels = [
        builder.rel(obj_id, "target"),
        builder.rel(repo_id, "source")
    ]
    if author_id:
        rels.append(builder.rel(author_id, "author"))

    # Events
    try:
        builder.add_event(
            Activities.PR_OPENED if is_pr else Activities.ISSUE_OPENED,
            node["createdAt"],
            rels
        )

        if node.get("closedAt"):
            builder.add_event(
                Activities.PR_CLOSED if is_pr else Activities.ISSUE_CLOSED,
                node["closedAt"],
                rels
            )

        if is_pr and node.get("mergedAt"):
            builder.add_event(
                Activities.PR_MERGED,
                node["mergedAt"],
                rels
            )
    except Exception as e:
        logger.error(f"Failed to create events for {obj_type} {node['number']}: {e}")
        return

    # Lifecycle events
    map_lifecycle_events(node, builder, repo_id, obj_id)
