import time
from typing import Generator, Dict, Any, Callable
from github2ocel.client.github_client import GitHubClient
from shared.logger import get_logger

logger = get_logger(__name__)


def _paginate_connection(
    client: GitHubClient,
    query: str,
    variables: Dict[str, Any],
    extract_container: Callable,
    total: int = 0,
    label: str = "nodes",
) -> Generator[Dict[str, Any], None, None]:
    """
    Core pagination loop.

    Logging philosophy: the paginator is infrastructure — it stays silent unless
    something noteworthy happens (multi-page progress, stuck cursor, errors).
    Per-entity summary logs belong in the fetcher or orchestrator, not here.
    """
    vars_ = {
        "owner": client.owner,
        "repo":  client.repo,
        "cursor": None,
        **variables
    }

    cursor    = None
    page      = 1
    extracted = 0

    while True:

        vars_["cursor"] = cursor

        try:
            response  = client.graphql(query, vars_)
            container = extract_container(response)
        except Exception as e:
            logger.error(f"[paginator] Failed on page {page} ({label}): {e}")
            raise

        nodes = container.get("nodes", [])

        for node in nodes:
            if node:
                extracted += 1
                yield node

        page_info  = container.get("pageInfo", {})
        has_next   = page_info.get("hasNextPage", False)
        new_cursor = page_info.get("endCursor")

        if not has_next or not new_cursor:
            # Only log completion if it took more than one page — single-page calls are noise
            if page > 1:
                logger.debug(f"[paginator] {label}: {page} pages, {extracted} nodes")
            break

        if new_cursor == cursor:
            logger.warning(f"[paginator] Cursor stuck at {cursor} ({label}). Stopping.")
            break

        # Progress heartbeat every 10 pages for long-running extractions
        if page % 10 == 0:
            gql       = client.rate_limiter.resources["graphql"]
            remaining = gql.get("remaining", "?")
            cost      = client.rate_limiter._last_graphql_cost
            reset_ts  = gql.get("reset")
            reset_str = time.strftime("%H:%M:%S", time.localtime(reset_ts)) if reset_ts else "?"
            total_str = f"/{total}" if total else ""
            logger.info(
                f"[paginator] {label} page={page} | {extracted}{total_str} nodes | "
                f"cost={cost} pts_left={remaining} resets={reset_str}"
            )

        cursor = new_cursor
        page  += 1


def paginate_nodes(
    client: GitHubClient,
    query: str,
    node_type: str,
    variables: Dict[str, Any],
    total: int = 0,
    label: str = "nodes",
) -> Generator[Dict[str, Any], None, None]:

    def extract(response):
        repo = response.get("repository")
        if not repo:
            raise RuntimeError(f"'repository' missing in GraphQL response for {node_type}")
        container = repo.get(node_type)
        if container is None:
            raise RuntimeError(f"'{node_type}' missing in repository response")
        return container

    yield from _paginate_connection(client, query, variables, extract, total=total, label=label)


def paginate_commit_history(
    client: GitHubClient,
    query: str,
    variables: Dict[str, Any],
) -> Generator[Dict[str, Any], None, None]:

    def extract(response):
        repo = response.get("repository")
        if not repo:
            raise RuntimeError("'repository' missing in GraphQL response")
        default_ref = repo.get("defaultBranchRef")
        if not default_ref:
            raise RuntimeError("'defaultBranchRef' is None — repo may be empty or have no default branch")
        return default_ref["target"]["history"]

    yield from _paginate_connection(client, query, variables, extract)


def paginate_nested(
    client: GitHubClient,
    query: str,
    parent_type: str,
    parent_number: int,
    nested_field: str,
    number_var: str = None,
    page_size: int = 50,
) -> Generator[Dict[str, Any], None, None]:

    var_name = number_var or f"{parent_type}Number"

    vars_ = {
        var_name:   int(parent_number),
        "pageSize": page_size,
        "cursor":   None,
    }

    def extract(response):
        repo = response.get("repository")
        if not repo:
            raise RuntimeError(f"'repository' missing in GraphQL response for {parent_type}.{nested_field}")
        parent = repo.get(parent_type)
        if not parent:
            raise RuntimeError(f"'{parent_type}' missing in repository response")
        return parent[nested_field]

    yield from _paginate_connection(client, query, vars_, extract)