from typing import List, Dict, Any, Optional

from github2ocel.config.settings import APIConfig
from github2ocel.extractor.graphql.paginator import paginate_nodes
from github2ocel.extractor.graphql.queries import ISSUES_QUERY, PRS_QUERY

def fetch_issues_and_prs(
    owner: str,
    repo: str,
    token: str,
    api_config: APIConfig,
    pages: Optional[int] = None,
    per_page: int = 50,
) -> List[Dict[str, Any]]:
    issues = paginate_nodes(
        ISSUES_QUERY, "issues",
        owner, repo, token, api_config,
        pages, per_page,
    )

    prs = paginate_nodes(
        PRS_QUERY, "pullRequests",
        owner, repo, token, api_config,
        pages, per_page,
    )

    return (
        [{"__type": "Issue", **i} for i in issues] +
        [{"__type": "PullRequest", **p} for p in prs]
    )
