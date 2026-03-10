from typing import Generator, Dict, Any, List
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nested
from github2ocel.extractor.graphql.queries import ISSUE_COMMENTS_QUERY
from shared.logger import get_logger

logger = get_logger(__name__)


def fetch_issue_comments(
    client: GitHubClient,
    issue_numbers: List[int],
    page_size: int = 50,
) -> Generator[Dict[str, Any], None, None]:

    logger.info(f"--- [Fetcher] Issue Comments for {len(issue_numbers)} Issues ---")

    total = 0
    skipped = 0

    for i, issue_number in enumerate(int(float(n)) for n in issue_numbers):
        if i > 0 and i % 50 == 0:
            gql = client.rate_limiter.resources["graphql"]
            logger.info(f"  [issue_comments] {i}/{len(issue_numbers)} issues | {total} comments | pts_left={gql.get('remaining','?')}")
        try:
            for comment in paginate_nested(
                client=client,
                query=ISSUE_COMMENTS_QUERY,
                parent_type="issue",
                parent_number=issue_number,
                nested_field="comments",
                number_var="issueNumber",
                page_size=page_size,
            ):
                comment["__issue_number"] = issue_number
                comment["__type"] = "IssueComment"
                yield comment
                total += 1

        except Exception as e:
            logger.warning(f"[fetch_issue_comments] Failed Issue#{issue_number}: {e}")
            skipped += 1
            continue

    logger.info(f"--- [Fetcher] Issue Comments done — {total} total, {skipped} Issues skipped ---")