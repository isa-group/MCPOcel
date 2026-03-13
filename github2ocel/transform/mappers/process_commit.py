from typing import Dict, Any, List

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, parse_commit_message, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user, ensure_commit_full
from github2ocel.transform.mappers.process_pull_request import process_pr_commit_link
from github2ocel.transform.utils.activity import Activities
from shared.ocel.model.models import ObjectInstance
from shared.logger import get_logger

logger = get_logger(__name__)


def process_commit_graphql(
    node: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str,
    commit_pr_map: Dict[str, List[int]] = None,
) -> None:
    """
    Process a commit node from COMMITS_QUERY (Phase 4).

    Responsibilities:
      - Insert / enrich the Commit object via ensure_commit_full (handles stub-over)
      - O2O: Commit → Author User (authored_by)
      - O2O: Commit → Committer User (committed_by), when distinct from author
      - O2O: Commit → Issue (from commit message refs like "Fixes #42")
      - O2O: PullRequest → Commit (contains_commit), resolved from:
              a) commit_pr_map built in Phase 2 (all extracted PRs)
              b) associatedPullRequests in the GraphQL node (default branch PRs)
      - Event: CommitCreated with CI summary attributes

    NOTE: Commit → File O2O is handled in Phase 4b (process_commit_files via REST).
          The `files` field is not present in the GraphQL commit node.
    """
    sha = node.get("oid")
    if not sha:
        logger.warning("Commit node missing OID. Skipping.")
        return

    # --- Extract author / committer ---
    author_wrapper    = node.get("author")    or {}
    committer_wrapper = node.get("committer") or {}

    author_user    = author_wrapper.get("user")    or {}
    committer_user = committer_wrapper.get("user") or {}

    author_login = (
        author_user.get("login")
        or author_wrapper.get("name")
        or None
    )
    committer_login = (
        committer_user.get("login")
        or committer_wrapper.get("name")
        or None
    )

    # --- Merge detection ---
    parents = node.get("parents") or {}
    is_merge_commit = (parents.get("totalCount") or 0) > 1

    # --- Parse commit message once ---
    message  = node.get("message", "")
    analysis = parse_commit_message(message) if message else {}

    # --- Timestamps ---
    committed_date = node.get("committedDate", "")
    authored_date  = node.get("authoredDate", "")
    ts = safe_timestamp(committed_date)

    # --- 1. Insert / enrich Commit object ---
    commit_id = ensure_commit_full(
        builder         = builder,
        repo_id         = repo_id,
        sha             = sha,
        committed_date  = committed_date,
        additions       = node.get("additions", 0),
        deletions       = node.get("deletions", 0),
        changed_files   = node.get("changedFilesIfAvailable", 0),
        message         = message,
        author_login    = author_login or "",
        authored_date   = authored_date,
        committer_login = committer_login or "",
        is_merge_commit = is_merge_commit,
        analysis        = analysis,  # reuse — avoids double parse
    )
    if not commit_id:
        return

    # --- 2. Author User O2O ---
    author_id = ensure_user(builder, repo_id, author_login, timestamp=ts)

    # --- 3. Committer User O2O (only when distinct from author) ---
    committer_id = None
    if committer_login and committer_login != author_login:
        committer_id = ensure_user(builder, repo_id, committer_login, timestamp=ts)

    # --- 4. Commit → Issue O2O (from message refs: "Fixes #42") ---
    commit_proxy  = ObjectInstance(object_id=commit_id, object_type="Commit")
    has_extra_rels = False

    for issue_num in analysis.get("issue_refs", []):
        try:
            issue_id = make_id(repo_id, "issue", issue_num)
            if builder.object_exists(issue_id):
                commit_proxy.add_rel(target_id=issue_id, qualifier="references_issue")
                has_extra_rels = True
        except Exception as e:
            logger.warning(f"Failed to link commit {sha[:7]} to issue {issue_num}: {e}")

    if has_extra_rels:
        builder.insert_object(commit_proxy)

    # --- 5. PullRequest → Commit O2O ---
    # Union of two sources:
    #   a) commit_pr_map (Phase 2): covers all extracted PRs regardless of branch
    #   b) associatedPullRequests (GraphQL node): covers default-branch PRs with full pagination
    pr_numbers: List[int] = list(commit_pr_map.get(sha, [])) if commit_pr_map else []

    for assoc_pr in (node.get("associatedPullRequests") or {}).get("nodes", []):
        n = assoc_pr.get("number")
        if n and int(n) not in pr_numbers:
            pr_numbers.append(int(n))

    for pr_number in pr_numbers:
        process_pr_commit_link(pr_number, sha, builder, repo_id)

    # --- 6. CI summary from checkSuites ---
    suites = (node.get("checkSuites") or {}).get("nodes") or []
    completed_suites = [s for s in suites if s.get("conclusion")]
    ci_status     = suites[0].get("status")       if suites           else None
    ci_conclusion = suites[0].get("conclusion")   if suites           else None
    ci_failed     = any(s.get("conclusion") == "FAILURE" for s in suites)

    # O2O: Commit → WorkflowRun (via checkSuite.workflowRun.databaseId)
    for suite in suites:
        wr = (suite.get("workflowRun") or {})
        db_id = wr.get("databaseId")
        if db_id:
            wr_id = make_id(repo_id, "workflow", db_id)
            if builder.object_exists(wr_id):
                commit_proxy2 = ObjectInstance(object_id=commit_id, object_type="Commit")
                commit_proxy2.add_rel(target_id=wr_id, qualifier="tested_by")
                builder.insert_object(commit_proxy2)

    # --- 7. CommitCreated event ---
    signature = node.get("signature") or {}

    relationships = [
        (commit_id, "created_item"),
        (repo_id,   "repository_context"),
    ]
    if author_id:
        relationships.append((author_id, "authored_by"))
    if committer_id:
        relationships.append((committer_id, "committed_by"))

    create_event(
        builder    = builder,
        event_type = Activities.COMMIT_CREATED,
        ts         = ts,
        attributes = {
            "source":           "graphql_api",
            "intent":           analysis.get("commit_type", ""),
            "is_merge_commit":  int(is_merge_commit),
            "is_verified":      int(signature.get("isValid", False)),
            "ci_status":        ci_status or "",
            "ci_conclusion":    ci_conclusion or "",
            "ci_failed":        int(ci_failed),
        },
        relationships=relationships,
    )