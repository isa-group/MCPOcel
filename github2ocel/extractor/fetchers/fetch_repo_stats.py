from shared.logger import get_logger
from github2ocel.client.github_client import GitHubClient
from github2ocel.extractor.graphql.queries import REPO_STATS_QUERY
from github2ocel.transform.model.model import RepoStats


logger = get_logger(__name__)

def fetch_repo_stats(client: GitHubClient) -> RepoStats:
   """Single cheap request (cost=1) to get all entity counts."""
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

       target = (repo.get("defaultBranchRef") or {}).get("target") or {}

       # With since: windowed count. Without since: both point to same totalCount.
       commits     = (target.get("history")    or {}).get("totalCount", 0)
       all_commits = (target.get("allHistory") or {}).get("totalCount", 0)

       stats = RepoStats(
           issues        = repo.get("issues",       {}).get("totalCount", 0),
           pull_requests = repo.get("pullRequests", {}).get("totalCount", 0),
           discussions   = repo.get("discussions",  {}).get("totalCount", 0),
           releases      = repo.get("releases",     {}).get("totalCount", 0),
           milestones    = repo.get("milestones",   {}).get("totalCount", 0),
           tags          = (repo.get("refs")  or {}).get("totalCount", 0),
           branches      = (repo.get("refs2") or {}).get("totalCount", 0),
           commits       = commits,
           reviews_est   = 0,
       )

       # Reviews estimation uses windowed PR count (all PRs — no since filter available)
       prs = stats.pull_requests
       if prs < 200:
           avg_reviews = 1.5
       elif prs < 1000:
           avg_reviews = 2.5
       else:
           avg_reviews = 3.5
       stats.reviews_est = int(prs * avg_reviews)

       window_str = f"since={since_iso[:10]}" if since_iso else "full history"
       logger.info(
           f"  [{window_str}] issues={stats.issues} prs={stats.pull_requests} "
           f"commits={commits} (total={all_commits}) "
           f"discussions={stats.discussions} remaining_points={rl.get('remaining', '?')}"
       )
       return stats

   except Exception as e:
       logger.warning(f"[Adaptive] Failed to fetch stats: {e} — using defaults")
       return RepoStats()