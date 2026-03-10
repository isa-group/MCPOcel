from typing import Generator, Dict, Any, List
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nested
from github2ocel.extractor.graphql.queries import PR_COMMITS_QUERY
from shared.logger import get_logger

logger = get_logger(__name__)

def fetch_pr_commits(
    client: GitHubClient,
    pr_numbers: List[int],
    page_size: int = 100,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield commit OID dicts for each PR, fully paginated.

    Each yielded dict:
      { "oid": str, "committedDate": str, "author": {...}, "__pr_number": int }

    Purpose: build PullRequest ──contains_commit──► Commit O2O.
    Full commit data (files, diffs, CI) comes from fetch_commits() over defaultBranch.

    Args:
        page_size: commits per page. 100 is GitHub's max and safe because
                   each commit node here is tiny (just oid + date + author).
    """
    logger.info(f"--- [Fetcher] PR Commits (O2O links) for {len(pr_numbers)} PRs ---")
    total = 0
    skipped = 0

    for i, pr_number in enumerate(int(float(n)) for n in pr_numbers):
        if i > 0 and i % 100 == 0:
            gql = client.rate_limiter.resources["graphql"]
            logger.info(f"  [pr_commits] {i}/{len(pr_numbers)} PRs | {total} links | pts_left={gql.get('remaining','?')}")
        try:
            pr_total = 0
            for commit_node in paginate_nested(
                client=client,
                query=PR_COMMITS_QUERY,
                parent_type="pullRequest",
                parent_number=pr_number,
                nested_field="commits",
                number_var="prNumber",
                page_size=page_size,
            ):
                if not commit_node:
                    continue
                commit = commit_node.get("commit") or {}
                oid = commit.get("oid")
                if not oid:
                    continue

                author = commit.get("author") or {}
                user = author.get("user") or {}

                yield {
                    "__type":      "PRCommitLink",
                    "__pr_number": pr_number,
                    "oid":         oid,
                    "committedDate": commit.get("committedDate"),
                    "author_login": user.get("login"),
                }
                total += 1
                pr_total += 1

            logger.debug(f"[fetch_pr_commits] PR#{pr_number}: {pr_total} commits")

        except Exception as e:
            logger.warning(f"[fetch_pr_commits] Failed PR#{pr_number}: {e}")
            skipped += 1
            continue

    logger.info(f"--- [Fetcher] PR Commits done — {total} links, {skipped} PRs skipped ---")