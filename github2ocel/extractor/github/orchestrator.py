import time
from typing import Dict, List, Tuple

from github2ocel.extractor.fetchers.utils.compute_page_sizes import compute_page_sizes
from github2ocel.transform.model.model import PageSizes, RepoStats
from shared.logger import get_logger
from shared.ocel.builder import OCELBuilder
from github2ocel.client.github_client import GitHubClient
from github2ocel.client.exceptions import (
    RateLimitError, RetryableError, GraphQLError, FatalError
)
from github2ocel.config.profiles import PROFILES

# Fetchers
from github2ocel.extractor.fetchers import (
    fetch_repo_stats,
    fetch_milestones,
    fetch_issues,
    fetch_pull_requests,
    fetch_branches,
    fetch_tags,
    fetch_pr_comments,
    fetch_pr_commits,
    fetch_issue_comments,
    fetch_pr_reviews,
    fetch_issue_timeline,
    fetch_pr_timeline,
    fetch_pr_threads,
    fetch_commits,
    fetch_deployments,
    fetch_workflow_runs,
    fetch_releases,
    fetch_discussions,
    fetch_commit_files
)

# Mappers
from github2ocel.transform.mappers import (
    process_milestone,
    process_branch,
    process_tag,
    process_issue,
    process_issue_comment,
    process_pull_request,
    process_pr_comment,
    process_pr_commit_link,
    process_review,
    process_review_thread,
    process_timeline_event,
    process_commit_graphql,
    process_deployment,
    process_workflow_run,
    apply_retry_links,
    process_release,
    process_discussion_node,
    process_commit_files
)

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

        # Collected commit SHAs for file enrichment (Phase 4b)
        self._commit_shas: List[str] = []

        # oid → pr_number map built in Phase 2, consumed in Phase 4
        # Allows process_commit_graphql to create PR→Commit O2O without
        # relying on object_exists() checks that fail due to phase ordering.
        self._commit_pr_map: Dict[str, List[int]] = {}

        # PRs/Issues that exceeded embedded limits → need overflow pagination
        self._overflow_pr_reviews:     List[int] = []
        self._overflow_pr_comments:    List[int] = []
        self._overflow_pr_commits:     List[int] = []
        self._overflow_pr_timeline:    List[int] = []
        self._overflow_issue_comments: List[int] = []
        self._overflow_issue_timeline: List[int] = []

        # Adaptive page sizes
        self._ps: PageSizes = PageSizes()

        # Active profile flags
        self._profile = client.ctx.profile
        self._flags = PROFILES[self._profile]
        logger.info(f"Extraction profile: {self._profile.value} — {self._flags}")

    # Runner
    def run(self) -> bool:
        phases = [
            ("Setup       — Repo stats",         self._phase_stats,          True),
            ("Init        — Seed objects",        self._initialization,       True),
            ("Phase 1     — Core objects",        self._phase1_core,          True),
            ("Phase 2     — Per-node detail",     self._phase2_detail,        True),
            ("Phase 3     — Reviews & Timeline",  self._phase3_dependent,     self._flags["withReviews"] or self._flags["withTimeline"]),
            ("Phase 4     — Commits",             self._phase4_commits,       True),
            ("Phase 4b    — Commit files",        self._phase4b_commit_files, self._flags.get("withFileObjects", False)),
            ("Phase 5     — Releases",            self._phase5_releases,      True),
            ("Phase 6     — DevOps",              self._phase6_devops,        True),
            ("Phase 7     — Knowledge base",      self._phase7_knowledge,     self._flags["withDiscussions"]),
        ]

        for name, fn, enabled in phases:
            if not enabled:
                logger.info(f" - {name} [SKIPPED by profile '{self._profile.value}']")
                continue

            # Phase 4b requires commits extracted in Phase 4
            if fn == self._phase4b_commit_files and not self._commit_shas:
                logger.info(f" - {name} [SKIPPED — no commits extracted in Phase 4]")
                continue

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
        self.repo_metrics, repo_obj = fetch_repo_stats(self.client, self.repo_id)
        self.builder.insert_object(repo_obj)
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
            issue_number = int(node["number"])
            self._issue_numbers.append(issue_number)
            self.stats["issues"] += 1

            # Populate overflow list: any issue with comments needs phase 2
            if (node.get("comments") or {}).get("totalCount", 0) > 0:
                self._overflow_issue_comments.append(issue_number)

            # Populate overflow list: any issue with relevant timeline events needs phase 3
            if (node.get("timelineItems") or {}).get("totalCount", 0) > 0:
                self._overflow_issue_timeline.append(issue_number)

        logger.info(
            f"  issues={self.stats['issues']} "
            f"(overflow_comments={len(self._overflow_issue_comments)} "
            f"overflow_timeline={len(self._overflow_issue_timeline)})"
        )

        real_reviews = 0
        for node in fetch_pull_requests(self.client, page_size=self._ps.pull_requests, total=self.repo_metrics.pull_requests):
            process_pull_request(node, self.builder, self.repo_id)
            pr_number = int(node["number"])
            self._pr_numbers.append(pr_number)
            self.stats["prs"] += 1
            real_reviews += (node.get("reviews") or {}).get("totalCount", 0)

            # Populate overflow lists: only PRs that actually have nested data
            # need phase 2/3 fetcher calls. Threshold is > 0 because phase 1
            # does not embed any nodes yet (totalCount only) — when pageInfo
            # is added to the queries, this switches to hasNextPage.
            if (node.get("comments") or {}).get("totalCount", 0) > 0:
                self._overflow_pr_comments.append(pr_number)
            if (node.get("commits") or {}).get("totalCount", 0) > 0:
                self._overflow_pr_commits.append(pr_number)
            if (node.get("reviews") or {}).get("totalCount", 0) > 0:
                self._overflow_pr_reviews.append(pr_number)
            if (node.get("timelineItems") or {}).get("totalCount", 0) > 0:
                self._overflow_pr_timeline.append(pr_number)

        logger.info(
            f"  prs={self.stats['prs']} "
            f"(overflow_comments={len(self._overflow_pr_comments)} "
            f"overflow_commits={len(self._overflow_pr_commits)} "
            f"overflow_reviews={len(self._overflow_pr_reviews)} "
            f"overflow_timeline={len(self._overflow_pr_timeline)})"
        )

        # Always update reviews_est with the real accumulated count —
        # must happen before compute_page_sizes regardless of the branch below.
        self.repo_metrics.reviews_est = real_reviews

        # Recalculate page sizes using actual extracted counts.
        # repo_metrics.pull_requests is the total repo count (no since filter),
        # but the per-PR nested phases (reviews, timeline, comments) only run
        # against the actual extracted PRs — recalibrate accordingly.
        actual_prs = self.stats["prs"]
        remaining = self.client.rate_limiter.resources["graphql"].get("remaining")
        if actual_prs < self.repo_metrics.pull_requests:
            self.repo_metrics.pull_requests = actual_prs
            self.repo_metrics.issues = self.stats["issues"]
            self._ps = compute_page_sizes(self.repo_metrics, remaining_points=remaining)
            logger.info(
                f"  [page sizes recalibrated — windowed extraction, "
                f"real reviews_est={real_reviews}]"
            )
        else:
            # Full history: PR count matches, but reviews_est is now exact.
            # Recalibrate to apply the real value to pr_reviews page size.
            self._ps = compute_page_sizes(self.repo_metrics, remaining_points=remaining)
            logger.info(
                f"  [page sizes recalibrated — full history, "
                f"real reviews_est={real_reviews}]"
            )

    # Phase 2: per-node detail (requires Phase 1 objects)
    def _phase2_detail(self):
        """
        Fully paginated comments and commit O2O links.
        Kept separate from Phase 1 so the base pass runs at full pageSize
        without being slowed down by nested pagination.

        Uses overflow lists populated in Phase 1 from totalCount fields:
        only issues/PRs that actually have nested data generate API calls.
        """
        # Issue comments — only issues with comments (overflow_issue_comments)
        if self._overflow_issue_comments:
            for comment in fetch_issue_comments(self.client, self._overflow_issue_comments, page_size=self._ps.issue_comments):
                process_issue_comment(comment, self.builder, self.repo_id)
                self.stats["issue_comments"] += 1
        logger.info(
            f"  issue_comments={self.stats['issue_comments']} "
            f"(from {len(self._overflow_issue_comments)}/{self.stats['issues']} issues)"
        )

        # PR commit OIDs — only PRs with commits (overflow_pr_commits)
        # process_pr_commit_link is intentionally not called here: Commit objects
        # don't exist yet (Phase 4), so object_exists() checks would all fail.
        # The map is passed to process_commit_graphql in Phase 4 instead.
        if self._overflow_pr_commits:
            for link in fetch_pr_commits(self.client, self._overflow_pr_commits, page_size=self._ps.pr_commits):
                oid = link.get("oid")
                pr_number = link.get("__pr_number")
                if oid and pr_number:
                    self._commit_pr_map.setdefault(oid, [])
                    if pr_number not in self._commit_pr_map[oid]:
                        self._commit_pr_map[oid].append(pr_number)
                self.stats["pr_commit_links"] += 1
        logger.info(
            f"  pr_commit_links={self.stats['pr_commit_links']} "
            f"({len(self._commit_pr_map)} unique OIDs mapped, "
            f"from {len(self._overflow_pr_commits)}/{self.stats['prs']} PRs)"
        )

        # PR comments — only PRs with comments (overflow_pr_comments)
        if self._overflow_pr_comments:
            for comment in fetch_pr_comments(self.client, self._overflow_pr_comments, page_size=self._ps.pr_comments):
                process_pr_comment(comment, self.builder, self.repo_id)
                self.stats["pr_comments"] += 1
        logger.info(
            f"  pr_comments={self.stats['pr_comments']} "
            f"(from {len(self._overflow_pr_comments)}/{self.stats['prs']} PRs)"
        )


    # Phase 3: dependent objects
    def _phase3_dependent(self):

        if self._flags["withReviews"]:
            with_rc = self._flags.get("withReviewComments", False)
            if self._overflow_pr_reviews:
                for review in fetch_pr_reviews(self.client, self._overflow_pr_reviews, page_size=self._ps.pr_reviews):
                    process_review(review, self.builder, self.repo_id, with_review_comments=with_rc)
                    self.stats["reviews"] += 1
            logger.info(
                f"  reviews={self.stats['reviews']} "
                f"(from {len(self._overflow_pr_reviews)}/{self.stats['prs']} PRs)"
            )
        else:
            logger.info("  reviews=SKIPPED (profile)")

        if self._flags["withTimeline"]:
            if self._overflow_pr_timeline:
                for event in fetch_pr_timeline(self.client, self._overflow_pr_timeline, page_size=self._ps.pr_timeline):
                    process_timeline_event(event, self.builder, self.repo_id)
                    self.stats["timeline_events"] += 1
            logger.info(
                f"  pr_timeline_events={self.stats['timeline_events']} "
                f"(from {len(self._overflow_pr_timeline)}/{self.stats['prs']} PRs)"
            )

            issue_tl_before = self.stats["timeline_events"]
            if self._overflow_issue_timeline:
                for event in fetch_issue_timeline(self.client, self._overflow_issue_timeline, page_size=self._ps.issue_timeline):
                    process_timeline_event(event, self.builder, self.repo_id)
                    self.stats["timeline_events"] += 1
            logger.info(
                f"  issue_timeline_events={self.stats['timeline_events'] - issue_tl_before} "
                f"(from {len(self._overflow_issue_timeline)}/{self.stats['issues']} issues)"
            )
        else:
            logger.info("  timeline=SKIPPED (profile)")

        if self._flags.get("withThreads", False):
            threads_resolved = 0
            for thread in fetch_pr_threads(self.client, self._overflow_pr_reviews):
                process_review_thread(thread, self.builder, self.repo_id)
                threads_resolved += 1
            logger.info(
                f"  review_threads={threads_resolved} "
                f"(from {len(self._overflow_pr_reviews)}/{self.stats['prs']} PRs)"
            )
        else:
            logger.info("  review_threads=SKIPPED (profile)")

    # Phase 4: commits
    def _phase4_commits(self):
        for node in fetch_commits(self.client, page_size=self._ps.commits):
            process_commit_graphql(node, self.builder, self.repo_id, self._commit_pr_map)
            self.stats["commits"] += 1
            if node.get("oid"):
                self._commit_shas.append(node["oid"])
        logger.info(f"  commits={self.stats['commits']} (SHAs queued for Phase 4b: {len(self._commit_shas)})")

        # Feature-branch commits in commit_pr_map were never processed by
        # process_commit_graphql (Phase 4 only walks the default branch).
        # Create their PR→Commit O2O links directly — process_pr_commit_link
        # will insert a minimal stub if the commit doesn't exist yet.
        unprocessed = set(self._commit_pr_map.keys()) - set(self._commit_shas)
        linked = 0
        for oid in unprocessed:
            for pr_number in self._commit_pr_map[oid]:
                process_pr_commit_link(pr_number, oid, self.builder, self.repo_id)
                linked += 1
        if unprocessed:
            logger.info(f"  feature-branch commit links: {linked} links for {len(unprocessed)} OIDs")

    # Phase 4b: file enrichment via REST (COMPLETE profile only)
    def _phase4b_commit_files(self):
        file_links = 0
        new_files  = 0
        for payload in fetch_commit_files(self.client, self._commit_shas, max_commits=self.client.config.max_commits_for_files):
            links, files = process_commit_files(payload, self.builder, self.repo_id)
            file_links += links
            new_files  += files
        self.stats["file_links"] = file_links
        self.stats["files"]      = new_files
        if file_links == 0 and new_files == 0:
            logger.info(f"  file enrichment skipped (see warning above)")
        else:
            logger.info(f"  file_objects={new_files} | commit_file_links={file_links}")

    # Phase 5: releases (after commits so O2O to tags/commits resolves correctly)
    def _phase5_releases(self):
        for node in fetch_releases(self.client, page_size=self._ps.releases):
            process_release(node, self.builder, self.repo_id)
            self.stats["releases"] += 1
        logger.info(f"  releases={self.stats['releases']}")

    # Phase 6: DevOps
    def _phase6_devops(self):
        for node in fetch_deployments(self.client, page_size=self._ps.deployments):
            process_deployment(node, self.builder, self.repo_id)
            self.stats["deployments"] += 1
        logger.info(f"  deployments={self.stats['deployments']}")

        # Accumulate (run_number, run_attempt) → run_id while iterating.
        # Needed to resolve retry_of O2O after all runs are inserted — a re-run's
        # predecessor may not exist yet when the re-run node is first processed.
        run_attempt_map: Dict[Tuple[int, int], str] = {}

        for node in fetch_workflow_runs(self.client, page_size=self._ps.workflow_runs):
            run_id = process_workflow_run(node, self.builder, self.repo_id)
            self.stats["workflow_runs"] += 1
            self.stats["workflow_jobs"] += len(node.get("extracted_jobs", []))

            run_number  = int(node.get("run_number") or 0)
            run_attempt = int(node.get("run_attempt") or 1)
            if run_id and run_number:
                run_attempt_map[(run_number, run_attempt)] = run_id

        logger.info(
            f"  workflow_runs={self.stats['workflow_runs']} "
            f"workflow_jobs={self.stats['workflow_jobs']}"
        )

        # Link re-run attempts: attempt N → attempt N-1 via O2O (retry_of)
        retries = apply_retry_links(run_attempt_map, self.builder)
        if retries:
            logger.info(f"  workflow_retry_links={retries}")

    # Phase 7: knowledge base
    def _phase7_knowledge(self):
        for node in fetch_discussions(self.client, page_size=self._ps.discussions):
            process_discussion_node(node, self.builder, self.repo_id)
            self.stats["discussions"] += 1
        logger.info(f"  discussions={self.stats['discussions']}")