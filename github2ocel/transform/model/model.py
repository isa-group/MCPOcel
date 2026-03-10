from dataclasses import dataclass
from typing import Optional

@dataclass
class RepoStats:
   issues:       int = 0
   pull_requests: int = 0
   discussions:  int = 0
   releases:     int = 0
   milestones:   int = 0
   tags:         int = 0
   branches:     int = 0
   commits:      int = 0
   reviews_est:  int = 0   # estimated: prs * avg_reviews_per_pr

@dataclass
class PageSizes:
   milestones:    int = 100
   branches:      int = 100
   tags:          int = 100
   issues:        int = 50
   pull_requests: int = 20
   commits:       int = 50
   releases:      int = 50
   discussions:   int = 50

   # Per-PR nested (used only for overflow pagination)
   pr_reviews:    int = 30
   pr_comments:   int = 50
   pr_commits:    int = 100
   pr_timeline:   int = 50

   # Per-Issue nested
   issue_comments: int = 50
   issue_timeline: int = 100

   # REST-based fetchers
   workflow_runs:  int = 100
   deployments:    int = 100

@dataclass
class ExtractionRange:
    since: Optional[str] = None  # ISO format
    until: Optional[str] = None  # ISO format

    @property
    def is_active(self) -> bool:
        return self.since is not None

@dataclass
class ExtractionContext:
    owner: str
    repo: str
    range: ExtractionRange
    page_sizes: PageSizes