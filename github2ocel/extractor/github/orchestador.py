import time
from typing import Dict, List

from github2ocel.extractor.fetchers.utils.compute_page_sizes import compute_page_sizes
from github2ocel.transform.model.model import PageSizes, RepoStats
from shared.logger import get_logger
from shared.ocel.builder import OCELBuilder
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.exceptions import (
    RateLimitError, RetryableError, GraphQLError, FatalError
)

# Fetchers
from github2ocel.extractor.fetchers import (
    fetch_repo_stats,
    fetch_milestones,
    fetch_issues,
    fetch_pull_requests,
    fetch_branches,
    fetch_tags,
)

# Mappers
from github2ocel.transform.mappers.process_milestone import process_milestone
from github2ocel.transform.mappers.process_branch import process_branch
from github2ocel.transform.mappers.process_tag import process_tag
from github2ocel.transform.mappers.process_issue import process_issue
from github2ocel.transform.mappers.process_pull_request import process_pull_request

logger = get_logger(__name__)

# Orchestrator
class Orchestrator:

    def __init__(
        self,
        client: GitHubClient,
        builder: OCELBuilder,
        repo_id: str,
        stats: Dict[str, int],
    ):
        self.client   = client
        self.builder  = builder
        self.repo_id  = repo_id
        self.stats    = stats

        # Collected
        self.repo_metrics: RepoStats = RepoStats() # Los contadores del repo
        self._pr_numbers:    List[int] = []
        self._issue_numbers: List[int] = []

        # PRs/Issues that exceeded embedded limits → need overflow pagination
        self._overflow_pr_reviews:   List[int] = []
        self._overflow_pr_comments:  List[int] = []
        self._overflow_pr_commits:   List[int] = []
        self._overflow_pr_timeline:  List[int] = []
        self._overflow_issue_comments: List[int] = []

        # Adaptive page sizes
        self._ps: PageSizes = PageSizes()

        # Date extraction
        self.since, self.until = self.client.ctx.time_window_iso

    # Runner
    def run(self) -> bool:
        phases = [
            ("Setup - Repo stats",                self._phase_stats),
            ("Initialization  — Seed objects",    self._initialization),
            ("Phase 1  — Core objects",           self._phase1_core),

        ]

        for name, fn in phases:
            logger.info(f" - {name}")
            t0 = time.time()
            ok = self._run_phase(name, fn)
            elapsed = time.time() - t0
            logger.info(f" * {name} [{'OK' if ok else 'FAILED'}] ({elapsed:.1f}s)")

            if not ok:
                logger.error(f"Pipeline aborted at '{name}'")
                return False

        return True

    def _run_phase(self, name: str, fn) -> bool:
        try:
            fn()
            return True
        except FatalError as e:
            logger.critical(f"[{name}] Fatal (auth/perms): {e}")
            return False
        except (RateLimitError, RetryableError, GraphQLError) as e:
            logger.error(f"[{name}] API error: {e}")
            return False
        except Exception as e:
            logger.exception(f"[{name}] Unexpected: {e}")
            return False

    def _phase_stats(self):
        self.repo_metrics = fetch_repo_stats(self.client)
        remaining = self.client.rate_limiter.resources["graphql"].get("remaining")
        self._ps = compute_page_sizes(self.repo_metrics, remaining_points=remaining)

    # Initialization
    def _initialization(self):
        for node in fetch_milestones(self.client, page_size=self._ps.milestones, total=self.repo_metrics.milestones):
            process_milestone(node, self.builder, self.repo_id)
            self.stats["milestones"] += 1
        logger.info(f"  milestones={self.stats['milestones']}")

        for node in fetch_branches(self.client): # REST
            process_branch(node, self.builder, self.repo_id)
            self.stats["branches"] += 1
        logger.info(f"  branches={self.stats['branches']}")

        for node in fetch_tags(self.client, page_size=self._ps.tags, total=self.repo_metrics.tags):
            process_tag(node, self.builder, self.repo_id)
            self.stats["tags"] += 1
        logger.info(f"  tags={self.stats['tags']}")

    # Phase 1: core objects
    def _phase1_core(self):
        for node in fetch_issues(self.client, page_size=self._ps.issues, total=self.repo_metrics.issues):
            process_issue(node, self.builder, self.repo_id)
            self._issue_numbers.append(int(node["number"]))
            self.stats["issues"] += 1
        logger.info(f"  issues={self.stats['issues']}")

        for node in fetch_pull_requests(self.client, page_size=self._ps.pull_requests, total=self.repo_metrics.pull_requests):
            process_pull_request(node, self.builder, self.repo_id)
            self._pr_numbers.append(int(node["number"]))
            self.stats["prs"] += 1
        logger.info(f"  prs={self.stats['prs']}")
