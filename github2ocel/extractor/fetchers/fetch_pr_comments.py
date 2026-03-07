from typing import Generator, Dict, Any, List
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nested
from github2ocel.extractor.graphql.queries import PR_COMMENTS_QUERY

from shared.logger import get_logger

logger = get_logger(__name__)

def fetch_pr_comments(
    client: GitHubClient,
    pr_numbers: List[int],
    page_size: int = 50,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield all PR comment nodes, fully paginated per PR.

    Each yielded dict has "__pr_number" injected for downstream mapping.
    Popular PRs can have 100s of comments — this ensures none are missed.
    """
    logger.info(f"--- [Fetcher] PR Comments for {len(pr_numbers)} PRs ---")
    total = 0
    skipped = 0

    for pr_number in (int(float(n)) for n in pr_numbers):
        try:
            pr_total = 0
            for comment in paginate_nested(
                client=client,
                query=PR_COMMENTS_QUERY,
                parent_type="pullRequest",
                parent_number=pr_number,
                nested_field="comments",
                number_var="prNumber",
                page_size=page_size,
            ):
                comment["__pr_number"] = pr_number
                comment["__type"] = "PRComment"
                yield comment
                total += 1
                pr_total += 1

            if pr_total > 0:
                logger.debug(f"[fetch_pr_comments] PR#{pr_number}: {pr_total} comments")

        except Exception as e:
            logger.warning(f"[fetch_pr_comments] Failed PR#{pr_number}: {e}")
            skipped += 1
            continue

    logger.info(f"--- [Fetcher] PR Comments done — {total} total, {skipped} PRs skipped ---")