"""
Fetch PR Reviews — separate query per PR number.
"""

from typing import Generator, Dict, Any, List
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nested
from github2ocel.extractor.graphql.queries import PR_REVIEWS_QUERY
from shared.logger import get_logger

logger = get_logger(__name__)


def fetch_pr_reviews(
    client: GitHubClient,
    pr_numbers: List[int],
    page_size: int = 30,
) -> Generator[Dict[str, Any], None, None]:
    logger.info(f"=== [Fetcher] PR Reviews for {len(pr_numbers)} PRs ===")
    total_reviews = 0

    for pr_number in (int(float(n)) for n in pr_numbers):
        try:
            for review in paginate_nested(
                client=client,
                query=PR_REVIEWS_QUERY,
                parent_type="pullRequest",
                parent_number=pr_number,
                nested_field="reviews",
                number_var="prNumber",
                page_size=page_size,
            ):
                review["__type"] = "Review"
                review["__pr_number"] = pr_number
                yield review
                total_reviews += 1

        except Exception as e:
            logger.warning(f"[fetch_pr_reviews] Failed for PR#{pr_number}: {e}")
            continue

    logger.info(f"=== [Fetcher] PR Reviews done — {total_reviews} reviews ===")