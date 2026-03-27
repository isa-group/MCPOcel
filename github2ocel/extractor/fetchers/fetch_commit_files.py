from typing import Generator, Dict, Any, List
from github2ocel.client.github_client import GitHubClient
from shared.logger import get_logger

logger = get_logger(__name__)

_CALLS_PER_SEC = 6.5  # ~sustained REST throughput for time estimates


def fetch_commit_files(
    client: GitHubClient,
    commit_shas: List[str],
    max_commits: int = 0,
) -> Generator[Dict[str, Any], None, None]:
    """
    For each SHA yield a dict:
        { "sha", "files": [{"path", "previous_path", "additions", "deletions",
                            "changes", "status"}],
          "verified", "verification_reason", "stats" }

    Uses REST GET /repos/{owner}/{repo}/commits/{sha}.

    max_commits: 0 = unlimited. If set and total exceeds it, skips with warning.
    """
    total = len(commit_shas)

    if max_commits and total > max_commits:
        logger.warning(
            f"[fetch_commit_files] {total} commits exceeds MAX_COMMITS_FOR_FILES="
            f"{max_commits} — skipping file enrichment. "
            f"Set MAX_COMMITS_FOR_FILES=0 or increase it to proceed."
        )
        return

    est_minutes = total / _CALLS_PER_SEC / 60
    if est_minutes > 2:
        logger.warning(
            f"[fetch_commit_files] {total} commits — estimated ~{est_minutes:.0f} min "
            f"at {_CALLS_PER_SEC:.0f} req/s. Set MAX_COMMITS_FOR_FILES=N to cap."
        )

    logger.info(f"--- [Fetcher] Commit Files ({total} commits, REST) ---")
    ok = 0
    skipped = 0

    for i, sha in enumerate(commit_shas):
        if i > 0 and i % 50 == 0:
            logger.info(f"  [commit_files] {i}/{total} | ok={ok} skipped={skipped}")
        try:
            data = client.rest(f"/repos/{client.owner}/{client.repo}/commits/{sha}")
            raw_files = data.get("files") or []
            files = [
                {
                    "path":              f.get("filename", ""),
                    "previous_path":     f.get("previous_filename"),
                    "additions":         f.get("additions", 0),
                    "deletions":         f.get("deletions", 0),
                    "changes":           f.get("changes", 0),
                    "status":            f.get("status", "modified"),
                }
                for f in raw_files
                if f.get("filename")
            ]

            commit_meta = data.get("commit") or {}
            verification = commit_meta.get("verification") or {}
            committer    = commit_meta.get("committer") or {}

            yield {
                "sha":                 sha,
                "committed_date":      committer.get("date", ""),
                "files":               files,
                "verified":            verification.get("verified", False),
                "verification_reason": verification.get("reason", ""),
                "stats":               data.get("stats") or {},
            }
            ok += 1
        except Exception as e:
            logger.warning(f"[fetch_commit_files] Failed SHA {sha[:7]}: {e}")
            skipped += 1
            continue

    logger.info(f"--- [Fetcher] Commit Files done — {ok} ok, {skipped} skipped ---")