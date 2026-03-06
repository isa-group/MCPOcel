from typing import Optional
from shared.logger import get_logger
from github2ocel.transform.model.model import RepoStats, PageSizes

logger = get_logger(__name__)

def compute_page_sizes(stats: RepoStats, remaining_points: Optional[int] = None) -> PageSizes:
   """
   Compute optimal page sizes given entity counts.

   Rules:
     - Small repo  (<200 PRs):  pageSize=50 for PRs (safe, few pages)
     - Medium repo (<1000 PRs): pageSize=30
     - Large repo  (≥1000 PRs): pageSize=20 (conservative, many embedded fields)
     - Very large  (≥3000 PRs): pageSize=10

   commits pageSize is independent — no embedded fields, safe at 50.
   """
   ps = PageSizes()

   prs = stats.pull_requests

   # PR embedded page size (the most critical — has reviews+timeline+comments inside)
   if prs < 200:
       ps.pull_requests = 50
   elif prs < 500:
       ps.pull_requests = 30
   elif prs < 1000:
       ps.pull_requests = 20
   elif prs < 3000:
       ps.pull_requests = 15
   else:
       ps.pull_requests = 10

   # Issues — no embedded heavy fields, safe higher
   if stats.issues < 500:
       ps.issues = 50
   elif stats.issues < 2000:
       ps.issues = 50
   else:
       ps.issues = 30

   # Commits — independent query, no nested cost
   if stats.commits < 2000:
       ps.commits = 50
   else:
       ps.commits = 50  # already safe, history query is cheap

   # If points are critically low, be more conservative
   if remaining_points is not None and remaining_points < 1000:
       logger.warning(f"[Adaptive] Low points ({remaining_points}) — reducing page sizes")
       ps.pull_requests = min(ps.pull_requests, 10)
       ps.issues        = min(ps.issues, 30)

   logger.info(
       f"[Adaptive] Page sizes → "
       f"prs={ps.pull_requests} issues={ps.issues} "
       f"commits={ps.commits} discussions={ps.discussions}"
   )
   return ps

