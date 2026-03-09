from shared.logger import get_logger
from github2ocel.client.github_client import GitHubClient
from github2ocel.extractor.graphql.queries import REPO_STATS_QUERY
from github2ocel.transform.model.model import RepoStats


logger = get_logger(__name__)

def fetch_repo_stats(client: GitHubClient) -> RepoStats:
   """Single cheap request (cost=1) to get all entity counts."""
   logger.info("--- [Adaptive] Fetching repository stats ---")

   try:
       payload = client.graphql(
           REPO_STATS_QUERY,
           {"owner": client.owner, "repo": client.repo},
       )
       repo = payload.get("repository", {})
       rl   = payload.get("rateLimit", {})

       commits = 0
       default_ref = repo.get("defaultBranchRef") or {}
       target = default_ref.get("target") or {}
       history = target.get("history") or {}
       commits = history.get("totalCount", 0)

       stats = RepoStats(
           issues        = repo.get("issues",       {}).get("totalCount", 0),
           pull_requests = repo.get("pullRequests", {}).get("totalCount", 0),
           discussions   = repo.get("discussions",  {}).get("totalCount", 0),
           releases      = repo.get("releases",     {}).get("totalCount", 0),
           milestones    = repo.get("milestones",   {}).get("totalCount", 0),
           tags          = (repo.get("refs")  or {}).get("totalCount", 0),
           branches      = (repo.get("refs2") or {}).get("totalCount", 0),
           commits       = commits,
           reviews_est   = 0,  # estimated below
       )
       # Reviews estimation based on repo size:
       prs = stats.pull_requests
       if prs < 200: # Small repos (avg ~1.5/PR).
           avg_reviews = 1.5
       elif prs < 1000: # Medium repos (avg ~2.5/PR).
           avg_reviews = 2.5
       else: # Large repos with formal workflows can reach 3-4 reviews per PR.
           avg_reviews = 3.5
       stats.reviews_est = int(prs * avg_reviews)

       logger.info(
           f"  issues={stats.issues} prs={stats.pull_requests} "
           f"commits={stats.commits} discussions={stats.discussions} "
           f"remaining_points={rl.get('remaining', '?')}"
       )
       return stats

   except Exception as e:
       logger.warning(f"[Adaptive] Failed to fetch stats: {e} — using defaults")
       return RepoStats()