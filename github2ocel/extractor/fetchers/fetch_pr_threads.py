from typing import Generator, Dict, Any, List
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nested
from github2ocel.extractor.graphql.queries import PR_THREADS_QUERY
from shared.logger import get_logger

logger = get_logger(__name__)


def fetch_pr_threads(
    client: GitHubClient,
    pr_numbers: List[int],
    page_size: int = 100,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield review thread nodes for each PR, fully paginated.

    Only called when withThreads=True (COMPLETE profile).
    Each yielded dict has '__pr_number' injected for downstream mapping.

    A review thread groups related inline comments and tracks resolution state.
    Only resolved threads generate OCEL events (ThreadResolved).
    """
    logger.info(f"--- [Fetcher] PR Review Threads for {len(pr_numbers)} PRs ---")
    total = 0
    skipped = 0

    for i, pr_number in enumerate(int(float(n)) for n in pr_numbers):
        if i > 0 and i % 100 == 0:
            gql = client.rate_limiter.resources["graphql"]
            logger.info(
                f"  [pr_threads] {i}/{len(pr_numbers)} PRs | "
                f"{total} threads | pts_left={gql.get('remaining','?')}"
            )
        try:
            for thread in paginate_nested(
                client=client,
                query=PR_THREADS_QUERY,
                parent_type="pullRequest",
                parent_number=pr_number,
                nested_field="reviewThreads",
                number_var="prNumber",
                page_size=page_size,
            ):
                if not thread:
                    continue
                thread["__pr_number"] = pr_number
                thread["__type"] = "ReviewThread"
                yield thread
                total += 1

        except Exception as e:
            logger.warning(f"[fetch_pr_threads] Failed for PR#{pr_number}: {e}")
            skipped += 1
            continue

    logger.info(
        f"--- [Fetcher] PR Review Threads done — {total} threads, {skipped} PRs skipped ---"
    )