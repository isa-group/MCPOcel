from typing import Optional
from shared.logger import get_logger
from github2ocel.transform.model.model import RepoStats, PageSizes

logger = get_logger(__name__)


def compute_page_sizes(stats: RepoStats, remaining_points: Optional[int] = None) -> PageSizes:
    """
    Calculate the optimal page sizes for each retriever.

    Mass scans in phase 1 (pull_requests, issues):
        Set to 50. PULL_REQUESTS_QUERY and ISSUES_QUERY do not include
        heavy nested data; only the totalCount fields are requested. 
    Phases 2/3: overflow retrievers (pr_reviews, pr_comments, etc.):
        Adaptive: these traverse the actual nested data per PR/issue
        and their cost varies depending on the volume of content, not the number of nodes.

    REST retrievers (workflow_runs, deployments):
        Always 100: no GraphQL cost.
    """
    ps = PageSizes()

    prs = stats.pull_requests

    # --- Phase 1 bulk scan: pull_requests ---
    # Scales to the size of the repository. PULL_REQUESTS_QUERY does not include revisions or
    # timeline nodes, but queries multiple fields: totalCount, tags,
    # assigned, statusCheckRollup and author —a weight sufficient for GitHub
    # to return a 502 with pageSize=50 on repositories with more than 1000 PRs.
    # The thresholds are high, but respect GitHub’s complexity limits.
    if prs < 500:
        ps.pull_requests = 50
    elif prs < 1000:
        ps.pull_requests = 40
    elif prs < 2000:
        ps.pull_requests = 30
    else:
        ps.pull_requests = 20

    # --- Phases 2/3 overflow: adaptive by content volume ---

    # PR reviews overflow — per-PR nested query
    reviews_est = stats.reviews_est
    if reviews_est < 200:
        ps.pr_reviews = 30
    elif reviews_est < 1000:
        ps.pr_reviews = 20
    else:
        ps.pr_reviews = 10   # large review volume — conservative per call

    # PR comments overflow — typically low per PR, safe at 50
    # PR commits overflow — 100 is GitHub max and commit nodes are tiny
    # PR timeline overflow — 50 is safe; timeline items are lightweight
    # (pr_comments, pr_commits, pr_timeline, issue_comments, issue_timeline
    #  keep their dataclass defaults — no adaptive logic needed)

    # Discussions — embedded comments+replies make each node expensive
    if stats.discussions < 200:
        ps.discussions = 50
    elif stats.discussions < 500:
        ps.discussions = 30
    else:
        ps.discussions = 20

    # --- Low-water guard: tighten overflow fetchers if points are critical ---
    if remaining_points is not None and remaining_points < 1000:
        logger.warning(f"[Adaptive] Low points ({remaining_points}) — reducing overflow page sizes")
        ps.pr_reviews  = min(ps.pr_reviews, 10)
        ps.pr_comments = min(ps.pr_comments, 30)
        ps.pr_timeline = min(ps.pr_timeline, 30)
        ps.discussions = min(ps.discussions, 20)

    logger.info(
        f"[Adaptive] Page sizes → "
        f"pull_requests={ps.pull_requests} issues={ps.issues} "
        f"commits={ps.commits} "
        f"pr_reviews={ps.pr_reviews} pr_comments={ps.pr_comments} "
        f"pr_commits={ps.pr_commits} pr_timeline={ps.pr_timeline} "
        f"discussions={ps.discussions} "
        f"(reviews_est={reviews_est})"
    )
    return ps