import time
from typing import Generator, Dict, Any
from github2ocel.client.github_client import GitHubClient
from shared.logger import get_logger

logger = get_logger(__name__)

def _paginate_connection(
    client: GitHubClient,
    query: str,
    variables: Dict[str, Any],
    extract_container,
    total: int = 0,
    label: str = "nodes",
) -> Generator[Dict[str, Any], None, None]:

    vars_ = {
        "owner": client.owner,
        "repo": client.repo,
        "cursor": None,
        **variables
    }

    cursor = None
    page = 1
    extracted = 0

    while True:

        vars_["cursor"] = cursor

        response = client.graphql(query, vars_)

        container = extract_container(response)

        nodes = container.get("nodes", [])

        for node in nodes:
            if node:
                extracted += 1
                yield node

        page_info = container.get("pageInfo", {})

        if not page_info.get("hasNextPage"):
            break

        new_cursor = page_info.get("endCursor")

        if new_cursor == cursor:
            logger.warning("Cursor stuck — stopping pagination")
            break
        if page % 10 == 0:
            gql       = client.rate_limiter.resources["graphql"]
            remaining = gql.get("remaining", "?")
            cost      = client.rate_limiter._last_graphql_cost
            reset_ts  = gql.get("reset")
            reset_str = time.strftime("%H:%M:%S", time.localtime(reset_ts)) if reset_ts else "?"
            total_str = f"/{total}" if total else ""
            log_fn = logger.info if total else logger.debug
            log_fn(
                f"[paginator] page={page} | {label}={extracted}{total_str} | "
                f"cost={cost} pts_left={remaining} resets={reset_str}"
            )

        cursor = new_cursor
        page += 1

def paginate_nodes(
    client: GitHubClient,
    query: str,
    node_type: str,
    variables: Dict[str, Any],
    total: int = 0,
    label: str = "nodes",
):
    def extract(response):
        repo = response["repository"]
        if not repo:
            raise RuntimeError("Repository not found in GraphQL response")
        return repo[node_type]

    yield from _paginate_connection(
        client,
        query,
        variables,
        extract,
        total=total,
        label=label,
    )

def paginate_commit_history(
    client: GitHubClient,
    query: str,
    variables: Dict[str, Any]
):

    def extract(response):

        return (
            response
            ["repository"]
            ["defaultBranchRef"]
            ["target"]
            ["history"]
        )

    yield from _paginate_connection(
        client,
        query,
        variables,
        extract
    )

def paginate_nested(
    client,
    query,
    parent_type,
    parent_number,
    nested_field,
    number_var: str = None,
    page_size: int = 50,
):

    var_name = number_var or f"{parent_type}Number"

    vars_ = {
        var_name: int(parent_number),
        "pageSize": page_size,
        "cursor": None
    }

    def extract(response):

        return (
            response
            ["repository"]
            [parent_type]
            [nested_field]
        )

    yield from _paginate_connection(
        client,
        query,
        vars_,
        extract
    )