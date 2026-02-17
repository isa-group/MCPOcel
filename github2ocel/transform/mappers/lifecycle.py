import uuid
import logging
from typing import Dict, Any
from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.helper import safe_timestamp, calculate_duration
from github2ocel.transform.utils.ensure import (
    ensure_comment, ensure_user, ensure_label, ensure_file,
    ensure_review_comment, ensure_commit, make_id
)
from github2ocel.transform.utils.activity import Activities
from shared.ocel.model.models  import ObjectInstance, Event

logger = logging.getLogger(__name__)

def map_lifecycle_events(node: Dict[str, Any], builder: OCELBuilder,
                         repo_id: str, target_id: str, is_pr: bool) -> None:
    """
    Lifecycle event orchestrator (static).
    Maps events that are not timeline events
    (current status of labels, comments, reviews).
    """
    _map_labels(node, builder, repo_id, target_id)
    _map_comments(node, builder, repo_id, target_id)

    # Reviews are exclusive to Pull Requests.
    if is_pr:
        _map_reviews(node, builder, repo_id, target_id)
        _map_pr_commits(node, builder, target_id, repo_id)
        _map_pr_check_runs(node, builder, target_id, repo_id)


def _map_labels(node: Dict[str, Any], builder: OCELBuilder,
                repo_id: str, target_id: str) -> None:
    """
    Map the current tags.
    NOTE: As it is a “snapshot”,
    it is assumed that they have existed since the creation
    of the Issue so as not to break the chronology, unless we use TimelineItems.
    """

    base_time = safe_timestamp(node.get("createdAt"))

    for lbl in node.get("labels", {}).get("nodes", []):
        if not lbl: continue

        name = lbl.get("name", "unknown")

        # ensure_label requiere repo_id
        label_id = ensure_label(builder, repo_id, lbl, timestamp=base_time)
        if not label_id:
            continue

        # Create Event (LABEL_ADDED)
        delay = calculate_duration(node.get("createdAt"), lbl.get("createdAt"))

        evt = Event(
            event_id=str(uuid.uuid4()),
            event_type=Activities.LABEL_ADDED,
            time=safe_timestamp(lbl.get("createdAt"), fallback=base_time),
            attributes={
                "event_class": "state_snapshot",
                "label_name": name,
                "time_to_label_seconds": delay,
                "source": "graphql_snapshot"
            }
        )
        evt.add_rel(target_id, "target")
        evt.add_rel(label_id, "label_added")

        builder.insert_event(evt)


def _map_comments(node: Dict[str, Any], builder: OCELBuilder,
                  repo_id: str, target_id: str) -> None:

    pr_created_at = node.get("createdAt")
    for comment in node.get("comments", {}).get("nodes", []):
        if not comment or not comment.get("createdAt"):
            continue

        created_at = safe_timestamp(comment["createdAt"])

        # Ensure Objects
        comment_id = ensure_comment(builder, repo_id, comment)
        author_login = comment.get("author", {}).get("login")
        author_id = ensure_user(builder, repo_id, author_login, timestamp=created_at)

        # Event: COMMENT_CREATED
        body = comment.get("body", "")
        resp_time = calculate_duration(pr_created_at, comment["createdAt"])
        evt_create = Event(
            event_id=str(uuid.uuid4()),
            event_type=Activities.COMMENT_CREATED,
            time=created_at,
            attributes={
                "source": "graphql",
                "response_time_sec": resp_time,
                "length": len(body),
                "has_code_block": 1 if "```" in body else 0,
                "reactions": comment.get("reactions", {}).get("totalCount", 0),
            }
        )
        evt_create.add_rel(comment_id, "content")
        evt_create.add_rel(target_id, "parent")
        if author_id:
            evt_create.add_rel(author_id, "author")

        builder.insert_event(evt_create)

        # Event: COMMENT_EDITED
        last_edited = comment.get("lastEditedAt")
        if last_edited and last_edited != comment["createdAt"]:
            edit_latency = calculate_duration(comment["createdAt"], last_edited)
            evt_edit = Event(
                event_id=str(uuid.uuid4()),
                event_type=Activities.COMMENT_EDITED,
                time=last_edited,
                attributes={
                    "source": "graphql",
                    "seconds_until_edit": edit_latency
                }
            )
            evt_edit.add_rel(comment_id, "comment_content")
            evt_edit.add_rel(target_id, "comment_parent")
            if author_id:
                evt_edit.add_rel(author_id, "editor")

            builder.insert_event(evt_edit)


def _map_reviews(node: Dict[str, Any], builder: OCELBuilder,
                 repo_id: str, target_id: str) -> None:

    activity_map = {
        "APPROVED": Activities.PR_REVIEW_APPROVED,
        "CHANGES_REQUESTED": Activities.PR_REVIEW_CHANGES_REQUESTED,
        "COMMENTED": Activities.PR_REVIEW_COMMENTED,
        "DISMISSED": Activities.PR_REVIEW_DISMISSED
    }
    pr_created = node.get("createdAt")

    for review in node.get("reviews", {}).get("nodes", []):
        if not review or not review.get("submittedAt"): continue

        ts = safe_timestamp(review["submittedAt"])

        author_login = review.get("author", {}).get("login")
        reviewer_id = ensure_user(builder, repo_id, author_login, timestamp=ts)

        state = review.get("state", "COMMENTED")
        activity = activity_map.get(state, Activities.PR_REVIEW)

        latency = calculate_duration(pr_created, review["submittedAt"])
        # Event: REVIEW...
        evt = Event(
            event_id=str(uuid.uuid4()),
            event_type=activity,
            time=ts,
            attributes={
                "review_state": state,
                "review_latency_sec": latency,
                "url": review.get("url", "")
            }
        )
        evt.add_rel(target_id, "reviewed_item")
        if reviewer_id:
            evt.add_rel(reviewer_id, "reviewer")

        builder.insert_event(evt)

        # Process inline code comments inside this review
        _map_review_line_comments(review, builder, repo_id, target_id)


def _map_review_line_comments(review: Dict[str, Any], builder: OCELBuilder,

                             repo_id: str, pr_id: str) -> None:

    for comment in review.get("comments", {}).get("nodes", []):
        if not comment or not comment.get("createdAt"): continue

        ts = safe_timestamp(comment["createdAt"])

        comment_id = ensure_review_comment(builder, repo_id, comment)
        author_id = ensure_user(builder, repo_id, comment.get("author", {}).get("login"), timestamp=ts)

        file_id = None
        if comment.get("path"):
            file_id = ensure_file(builder, repo_id, comment["path"], timestamp=ts)

        rels = [
            {"objectId": comment_id, "qualifier": "comment_content"},
            {"objectId": pr_id, "qualifier": "pull_request"}
        ]
        if author_id:
            rels.append({"objectId": author_id, "qualifier": "author"})

        if file_id:
            rels.append({"objectId": file_id, "qualifier": "file_context"})

        # Event: REVIEW_COMMENT_CREATED
        ts = safe_timestamp(comment["createdAt"])
        time_to_comment = calculate_duration(review.get("createdAt"), comment["createdAt"])
        evt = Event(
            event_id=str(uuid.uuid4()),
            event_type=Activities.REVIEW_COMMENT_CREATED,
            time=ts,
            attributes={
                "path": comment.get("path", ""),
                "position": str(comment.get("position", "")),
                "length": len(comment.get("body", "")),
                "time_to_review_seconds": time_to_comment
            }
        )

        evt.add_rel(comment_id, "comment_content")
        evt.add_rel(pr_id, "pull_request")

        if author_id: evt.add_rel(author_id, "author")
        if file_id: evt.add_rel(file_id, "file_context")

        builder.insert_event(evt)


def _map_pr_commits(node: Dict[str, Any], builder: OCELBuilder, pr_id: str, repo_id: str) -> None:

    commits_conn = node.get("commits")
    if not commits_conn:
        return

    commit_nodes = commits_conn.get("nodes", [])

    for c_node in commit_nodes:
        commit = c_node.get("commit")
        if not commit:
            continue

        sha = commit.get("oid")
        ts_commit = safe_timestamp(commit.get("committedDate"))

        commit_id = ensure_commit(builder, repo_id, sha, timestamp=ts_commit)

        pr_proxy = ObjectInstance(object_id=pr_id, object_type="PullRequest")
        pr_proxy.add_rel(target_id=commit_id, qualifier="contains_commit")
        builder.insert_object(pr_proxy)

        lead_time = calculate_duration(commit.get("committedDate"), node.get("createdAt"))
        evt_merge = Event(
            event_id=str(uuid.uuid4()),
            event_type="CommitIntegrated", # 'CommitMerged'
            time=ts_commit,
            attributes={
                "sha": sha,
                "integration_lead_time": lead_time,
                "message_summary": commit.get("message", "")[:100]
            }
        )

        # Link Commit -> PR
        evt_merge.add_rel(commit_id, "integrated_item")
        evt_merge.add_rel(pr_id, "target_pull_request")

        builder.insert_event(evt_merge)


def _map_pr_check_runs(node: Dict[str, Any], builder: OCELBuilder, pr_id: str, repo_id: str) -> None:
    """
    Maps the individual “Checks” (GitHub Actions Jobs) linked to a PR.
    It is called from issues_prs.py when we process a Pull Request.
    """
    rollup = node.get("statusCheckRollup")
    if not rollup: return

    check_nodes = rollup.get("contexts", {}).get("nodes", [])

    for run in check_nodes:
        # Only CheckRuns (Actions)
        if run.get("__typename") != "CheckRun":
            continue

        run_db_id = run.get("id") # ID base64 de GraphQL o numérico
        if not run_db_id: continue

        ts_start = safe_timestamp(run.get("startedAt"))

        # Hash or ID raw
        job_id = make_id(repo_id, "job", run_db_id)

        # Objet WorkflowJob
        job_obj = ObjectInstance(object_id=job_id, object_type="WorkflowJob")
        job_obj.add_snapshot(
            time=ts_start,
            attributes={
                "name": run.get("name"),
                "url": run.get("detailsUrl"),
                "conclusion": run.get("conclusion", "pending")
            }
        )

        # Validate PR
        pr_proxy = ObjectInstance(object_id=pr_id, object_type="PullRequest")
        pr_proxy.add_rel(target_id=job_id, qualifier="validated_by_job")

        # builder.insert_object(job_obj)
        builder.insert_object(pr_proxy)

        # Started
        if run.get("startedAt"):
            evt_start = Event(
                event_id=str(uuid.uuid4()),
                event_type=Activities.JOB_STARTED,
                time=ts_start,
                attributes={"source": "graphql_checks"}
            )
            evt_start.add_rel(job_id, "job_execution")
            evt_start.add_rel(pr_id, "pull_request_context")

            builder.insert_event(evt_start)


        # Completed
        if run.get("completedAt"):
            ts_end = safe_timestamp(run["completedAt"])
            duration = calculate_duration(run.get("startedAt"), run.get("completedAt"))

            evt_end = Event(
                event_id=str(uuid.uuid4()),
                event_type=Activities.JOB_COMPLETED,
                time=ts_end,
                attributes={
                    "conclusion": run.get("conclusion"),
                    "duration_seconds": duration,
                    "source": "graphql_checks"
                }
            )
            evt_end.add_rel(job_id, "job_execution")
            evt_end.add_rel(pr_id, "pull_request_context")

            builder.insert_event(evt_end)


def _map_review_threads(node, builder, pr_id, repo_id):
    for thread in node.get("reviewThreads", {}).get("nodes", []):
        thread_id = make_id(repo_id, "thread", thread["id"])
        
        thread_obj = ObjectInstance(object_id=thread_id, object_type="ReviewThread")
        thread_obj.add_snapshot(
            time=safe_timestamp(thread.get("createdAt")),
            attributes={
                "is_resolved": int(thread.get("isResolved", False)),
                "resolved_by": thread.get("resolvedBy", {}).get("login")
            }
        )
        builder.insert_object(thread_obj)
        
        if thread.get("isResolved"):
            evt = Event(
                event_type=Activities.THREAD_RESOLVED,
                time=safe_timestamp(thread.get("resolvedAt")),
                attributes={"resolver": thread.get("resolvedBy", {}).get("login")}
            )
            evt.add_rel(thread_id, "thread")
            evt.add_rel(pr_id, "pull_request")
            builder.insert_event(evt)