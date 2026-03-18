from dataclasses import dataclass
from typing import Optional

@dataclass
class RepoStats:
    # --- Entity counts (adaptive page sizing) ---
    issues:        int = 0            # windowed (since filter applied)
    all_issues:    int = 0            # full history, no time filter
    pull_requests: int = 0
    discussions:   int = 0
    releases:      int = 0
    milestones:    int = 0
    tags:          int = 0
    branches:      int = 0
    commits:       int = 0        # windowed (since filter applied)
    all_commits:   int = 0        # full history, no time filter
    deployments:   int = 0
    reviews_est:   int = 0        # estimated: prs * avg_reviews_per_pr

    # --- Repository metadata (for the Repository OCEL object) ---
    name_with_owner:   str  = ""
    description:       str  = ""
    created_at:        str  = ""
    updated_at:        str  = ""
    pushed_at:         str  = ""
    default_branch:    str  = "main"
    is_private:        bool = False
    is_fork:           bool = False
    is_archived:       bool = False
    is_disabled:       bool = False
    stars:             int  = 0
    forks:             int  = 0
    watchers:          int  = 0
    disk_usage_kb:     int  = 0
    primary_language:  str  = ""
    license_spdx:      str  = ""
    license_name:      str  = ""
    has_issues:        bool = True
    has_discussions:   bool = False
    has_wiki:          bool = False


@dataclass
class PageSizes:
   milestones:    int = 100
   branches:      int = 100
   tags:          int = 100
   issues:        int = 50
   pull_requests: int = 30
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