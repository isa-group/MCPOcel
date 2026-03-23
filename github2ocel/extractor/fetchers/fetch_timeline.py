from typing import Generator, Dict, Any, List
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.paginator import paginate_nested
from github2ocel.extractor.graphql.queries import PR_TIMELINE_QUERY, ISSUE_TIMELINE_QUERY
from shared.logger import get_logger

logger = get_logger(__name__)


def fetch_pr_timeline(
    client: GitHubClient,
    pr_numbers: List[int],
    page_size: int = 100,
    pr_head_ref_map: Dict[int, str] = None,
) -> Generator[Dict[str, Any], None, None]:

    logger.info(f"--- [Fetcher] PR Timelines for {len(pr_numbers)} PRs ---")
    total = 0

    for i, pr_number in enumerate(int(float(n)) for n in pr_numbers):
        if i > 0 and i % 100 == 0:
            gql = client.rate_limiter.resources["graphql"]
            logger.info(f"  [pr_timeline] {i}/{len(pr_numbers)} PRs | {total} events | pts_left={gql.get('remaining','?')}")
        try:
            for item in paginate_nested(
                client=client,
                query=PR_TIMELINE_QUERY,
                parent_type="pullRequest",
                parent_number=pr_number,
                nested_field="timelineItems",
                number_var="prNumber",
                page_size=page_size,
            ):
                if not item or not item.get("__typename"):
                    continue
                item["__pr_number"] = pr_number
                item["__parent_type"] = "PullRequest"
                # Inject head branch name for BranchMerged O2O resolution
                if pr_head_ref_map:
                    item["__pr_head_ref"] = pr_head_ref_map.get(pr_number, "")
                yield item
                total += 1

        except Exception as e:
            logger.warning(f"[fetch_pr_timeline] Failed for PR#{pr_number}: {e}")
            continue

    logger.info(f"--- [Fetcher] PR Timelines done — {total} events ---")

def fetch_issue_timeline(
    client: GitHubClient,
    issue_numbers: List[int],
    page_size: int = 100,
) -> Generator[Dict[str, Any], None, None]:
    logger.info(f"--- [Fetcher] Issue Timelines for {len(issue_numbers)} Issues ---")
    total = 0

    for i, issue_number in enumerate(int(float(n)) for n in issue_numbers):
        if i > 0 and i % 50 == 0:
            gql = client.rate_limiter.resources["graphql"]
            logger.info(f"  [issue_timeline] {i}/{len(issue_numbers)} issues | {total} events | pts_left={gql.get('remaining','?')}")
        try:
            for item in paginate_nested(
                client=client,
                query=ISSUE_TIMELINE_QUERY,
                parent_type="issue",
                parent_number=issue_number,
                nested_field="timelineItems",
                number_var="issueNumber",
                page_size=page_size,
            ):
                if not item or not item.get("__typename"):
                    continue
                item["__issue_number"] = issue_number
                item["__parent_type"] = "Issue"
                yield item
                total += 1

        except Exception as e:
            logger.warning(f"[fetch_issue_timeline] Failed for Issue#{issue_number}: {e}")
            continue

    logger.info(f"--- [Fetcher] Issue Timelines done — {total} events ---")