from datetime import datetime, timezone

from shared.logger import get_logger
from shared.ocel.model.models import ObjectInstance
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.exceptions import FatalError
from github2ocel.extractor.graphql.queries import REPO_STATS_QUERY
from github2ocel.transform.model.model import RepoStats

logger = get_logger(__name__)


def fetch_repo_stats(client: GitHubClient, repo_id: str) -> tuple[RepoStats, ObjectInstance]:
    """
    Single cheap GraphQL request (cost=1) that:
      1. Returns entity counts for adaptive page sizing.
      2. Builds and returns the Repository ObjectInstance with full metadata.

    By doing both here we avoid a second API call and ensure the Repository
    object is created from the source of truth (GitHub API) instead of from
    environment variables.
    """
    logger.info("--- [Adaptive] Fetching repository stats ---")

    since_iso, _ = client.time_window_iso   # None if no EXTRACT_SINCE_DAYS

    try:
        payload = client.graphql(
            REPO_STATS_QUERY,
            {
                "owner":    client.owner,
                "repo":     client.repo,
                "since":    since_iso,       # DateTime  — for issues filterBy
                "sinceGit": since_iso,       # GitTimestamp — for commit history
            },
        )
        repo = payload.get("repository", {})
        rl   = payload.get("rateLimit", {})

        default_ref = repo.get("defaultBranchRef") or {}
        target      = default_ref.get("target") or {}

        # Windowed count vs. full history
        commits     = (target.get("history")    or {}).get("totalCount", 0)
        all_commits = (target.get("allHistory") or {}).get("totalCount", 0)

        # --- Build RepoStats (counts + metadata) ---
        stats = RepoStats(
            # Windowed counts (since filter applied where supported)
            issues        = repo.get("issues",       {}).get("totalCount", 0),
            # Full history counts (for conservative page sizing)
            all_issues    = repo.get("allIssues",    {}).get("totalCount", 0),
            pull_requests = repo.get("pullRequests", {}).get("totalCount", 0),
            discussions   = repo.get("discussions",  {}).get("totalCount", 0),
            releases      = repo.get("releases",     {}).get("totalCount", 0),
            milestones    = repo.get("milestones",   {}).get("totalCount", 0),
            deployments   = repo.get("deployments",  {}).get("totalCount", 0),
            tags          = (repo.get("refs")  or {}).get("totalCount", 0),
            branches      = (repo.get("refs2") or {}).get("totalCount", 0),
            commits       = commits,
            all_commits   = all_commits,

            # Metadata
            name_with_owner  = repo.get("nameWithOwner", ""),
            description      = repo.get("description") or "",
            created_at       = repo.get("createdAt", ""),
            updated_at       = repo.get("updatedAt", ""),
            pushed_at        = repo.get("pushedAt", ""),
            default_branch   = default_ref.get("name", "main"),
            is_private       = repo.get("isPrivate", False),
            is_fork          = repo.get("isFork", False),
            is_archived      = repo.get("isArchived", False),
            is_disabled      = repo.get("isDisabled", False),
            stars            = repo.get("stargazerCount", 0),
            forks            = repo.get("forkCount", 0),
            watchers         = (repo.get("watchers") or {}).get("totalCount", 0),
            disk_usage_kb    = repo.get("diskUsage", 0) or 0,
            primary_language = (repo.get("primaryLanguage") or {}).get("name", ""),
            license_spdx     = (repo.get("licenseInfo") or {}).get("spdxId", ""),
            license_name     = (repo.get("licenseInfo") or {}).get("name", ""),
            has_issues       = repo.get("hasIssuesEnabled", True),
            has_discussions  = repo.get("hasDiscussionsEnabled", False),
            has_wiki         = repo.get("hasWikiEnabled", False),
        )

        # Reviews estimation (no direct count available via GraphQL)
        prs = stats.pull_requests
        if prs < 200:
            avg_reviews = 1.5
        elif prs < 1000:
            avg_reviews = 2.5
        else:
            avg_reviews = 3.5
        stats.reviews_est = int(prs * avg_reviews)

        # --- Build Repository ObjectInstance ---
        repo_obj = _build_repository_object(repo_id, stats)

        window_str = f"since={since_iso[:10]}" if since_iso else "full history"
        logger.info(
            f"  [{window_str}] issues={stats.issues} (total={stats.all_issues}) "
            f"prs={stats.pull_requests} "
            f"commits={commits} (total={all_commits}) "
            f"discussions={stats.discussions} remaining_points={rl.get('remaining', '?')}"
        )
        logger.info(
            f"  repo metadata: {stats.name_with_owner} | "
            f"{'private' if stats.is_private else 'public'} | "
            f"stars={stats.stars} | forks={stats.forks} | "
            f"lang={stats.primary_language or 'n/a'} | "
            f"branch={stats.default_branch}"
        )

        return stats, repo_obj

    except FatalError:
        # Auth failures, repo not found — no point continuing the pipeline
        raise
    except Exception as e:
        logger.warning(f"[Adaptive] Failed to fetch stats: {e} — using defaults")
        fallback_obj = _build_repository_object(repo_id, RepoStats())
        return RepoStats(), fallback_obj


def _build_repository_object(repo_id: str, stats: RepoStats) -> ObjectInstance:
    """Constructs the Repository ObjectInstance from RepoStats metadata."""

    # Use the repo's last updated timestamp as the snapshot time so OCEL
    # reflects when the state actually changed, not when extraction ran.
    snapshot_ts = stats.updated_at or datetime.now(timezone.utc).isoformat()

    repo_obj = ObjectInstance(object_id=repo_id, object_type="Repository")
    repo_obj.add_snapshot(
        time=snapshot_ts,
        attributes={
            "name":             stats.name_with_owner,
            "description":      stats.description,
            "default_branch":   stats.default_branch,
            "visibility":       "private" if stats.is_private else "public",
            "is_fork":          stats.is_fork,
            "is_archived":      stats.is_archived,
            "is_disabled":      stats.is_disabled,
            "stars":            stats.stars,
            "forks":            stats.forks,
            "watchers":         stats.watchers,
            "disk_usage_kb":    stats.disk_usage_kb,
            "primary_language": stats.primary_language,
            "license":          stats.license_spdx,
            "has_issues":       stats.has_issues,
            "has_discussions":  stats.has_discussions,
            "has_wiki":         stats.has_wiki,
            "created_at":       stats.created_at,
            "pushed_at":        stats.pushed_at,
        },
    )
    return repo_obj