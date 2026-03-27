from typing import Dict, Any, List

from shared.ocel.builder import OCELBuilder
from shared.ocel.model.models import ObjectInstance
from github2ocel.transform.utils.helper import make_id, parse_commit_message, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user, ensure_commit_full
from github2ocel.transform.mappers.process_pull_request import process_pr_commit_link
from github2ocel.transform.utils.activity import Activities
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
      - Insert / enrich the Commit object via ensure_commit_full
      - O2O: Commit → Author (authored_by)
      - O2O: Commit → Committer (committed_by), only when distinct from author
      - O2O: Commit → Signer (signed_by), when a valid GPG/SSH signature exists
      - O2O: Commit → Issue, from message refs like "Fixes #42"
      - O2O: Commit → WorkflowRun, via checkSuite.workflowRun.databaseId
      - O2O: PullRequest → Commit (contains_commit), from two sources:
               a) commit_pr_map built in Phase 2 (all extracted PRs, any branch)
               b) associatedPullRequests in the node (default-branch fallback,
                  capped at first: 5 — commit_pr_map is authoritative)
      - Event: CommitCreated with CI summary and signature attributes

    NOTE: Commit → File O2O is handled in Phase 4b (process_commit_files, REST).
    """
    sha = node.get("oid")
    if not sha:
        logger.warning("Commit node missing OID. Skipping.")
        return

    # Identity extraction
    author_wrapper    = node.get("author")    or {}
    committer_wrapper = node.get("committer") or {}
    signature = node.get("signature") or {}

    author_login = (
        (author_wrapper.get("user") or {}).get("login")
        or author_wrapper.get("name")
        or None
    )
    committer_login = (
        (committer_wrapper.get("user") or {}).get("login")
        or committer_wrapper.get("name")
        or None
    )
    signer_login = (signature.get("signer") or {}).get("login") or None
    is_verified  = int(bool(signature.get("isValid")))

    # Merge detection
    is_merge_commit = ((node.get("parents") or {}).get("totalCount") or 0) > 1

    # Commit message - parsed once, reused everywhere
    message  = node.get("message") or ""
    analysis = parse_commit_message(message) if message else {}

    # Timestamps
    committed_date = node.get("committedDate") or ""
    authored_date  = node.get("authoredDate")  or ""
    ts = safe_timestamp(committed_date)

    # 1. Commit object (insert or enrich stub from earlier phase)
    commit_id = ensure_commit_full(
        builder         = builder,
        repo_id         = repo_id,
        sha             = sha,
        committed_date  = committed_date,
        additions       = node.get("additions", 0),
        deletions       = node.get("deletions", 0),
        changed_files   = node.get("changedFilesIfAvailable", 0),
        message         = message,
        author_login    = author_login    or "",
        authored_date   = authored_date,
        committer_login = committer_login or "",
        is_merge_commit = is_merge_commit,
        analysis        = analysis,
    )
    if not commit_id:
        return

    # 2. User O2Os (author, committer, signer)
    author_id    = ensure_user(builder, repo_id, author_login, timestamp=ts) if author_login    else None
    committer_id = ensure_user(builder, repo_id, committer_login, timestamp=ts) if committer_login and committer_login != author_login else None
    signer_id    = ensure_user(builder, repo_id, signer_login,    timestamp=ts) if signer_login    else None

    user_rels = [
        (author_id,    "authored_by")  if author_id    else None,
        (committer_id, "committed_by") if committer_id else None,
        (signer_id,    "signed_by")    if signer_id    else None,
    ]
    user_rels = [(oid, q) for oid, q in (r for r in user_rels if r)]
    if user_rels:
        proxy = ObjectInstance(object_id=commit_id, object_type="Commit")
        for oid, qualifier in user_rels:
            proxy.add_rel(oid, qualifier)
        builder.insert_object(proxy)

    # 3. Issue O2Os (commit message refs)
    issue_rels = []
    for issue_num in analysis.get("issue_refs", []):
        try:
            issue_id = make_id(repo_id, "issue", issue_num)
            if builder.object_exists(issue_id):
                issue_rels.append(issue_id)
        except Exception as e:
            logger.warning(f"[process_commit] {sha[:7]} → issue {issue_num}: {e}")

    if issue_rels:
        proxy = ObjectInstance(object_id=commit_id, object_type="Commit")
        for issue_id in issue_rels:
            proxy.add_rel(issue_id, "references_issue")
        builder.insert_object(proxy)

    # 4. PullRequest → Commit O2Os
    pr_numbers: List[int] = list(commit_pr_map.get(sha, [])) if commit_pr_map else []
    for assoc in (node.get("associatedPullRequests") or {}).get("nodes", []):
        n = assoc.get("number")
        if n and int(n) not in pr_numbers:
            pr_numbers.append(int(n))
    for pr_number in pr_numbers:
        process_pr_commit_link(pr_number, sha, builder, repo_id)

    # 5. CI suite analysis
    suites           = (node.get("checkSuites") or {}).get("nodes") or []
    completed_suites = [s for s in suites if s.get("conclusion")]

    # Use the first completed suite for the summary attributes — avoids
    # reporting IN_PROGRESS status for a suite that finished by the time
    # the commit was extracted but was fetched before completion.
    # Falls back to the first suite overall if none have concluded yet.
    representative   = completed_suites[0] if completed_suites else (suites[0] if suites else {})
    ci_status        = representative.get("status")     or ""
    ci_conclusion    = representative.get("conclusion") or ""
    ci_failed        = any(s.get("conclusion") == "FAILURE" for s in suites)
    ci_completed_pct = round(len(completed_suites) / len(suites) * 100) if suites else 0

    # WorkflowRun O2Os — only for suites that have a linked run
    wr_proxy_built = False
    for suite in suites:
        db_id = (suite.get("workflowRun") or {}).get("databaseId")
        if not db_id:
            continue
        wr_id = make_id(repo_id, "workflow", db_id)
        if builder.object_exists(wr_id):
            if not wr_proxy_built:
                wr_proxy = ObjectInstance(object_id=commit_id, object_type="Commit")
                wr_proxy_built = True
            wr_proxy.add_rel(wr_id, "tested_by")
    if wr_proxy_built:
        builder.insert_object(wr_proxy)

    # 6. CommitCreated event
    event_rels = [
        (commit_id, "subject"),
        (repo_id,   "context"),
    ]
    if author_id:
        event_rels.append((author_id, "authored_by"))
    if committer_id:
        event_rels.append((committer_id, "committed_by"))
    if signer_id:
        event_rels.append((signer_id, "signed_by"))

    create_event(
        builder    = builder,
        event_type = Activities.COMMIT_CREATED,
        ts         = ts,
        attributes = {
            "source":            "graphql",
            "intent":            analysis.get("commit_type", ""),
            "is_merge_commit":   int(is_merge_commit),
            "is_verified":       is_verified,
            "ci_status":         ci_status,
            "ci_conclusion":     ci_conclusion,
            "ci_failed":         int(ci_failed),
            "ci_completed_pct":  ci_completed_pct,
        },
        relationships=event_rels,
    )