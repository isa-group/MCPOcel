# shared
from shared.logger import  get_logger

# github2ocel
from github2ocel.config.context import RepoContext
from github2ocel.client.github_client import GitHubClient
from github2ocel.transform.builder import OCELBuilder
from github2ocel.transform.rest_mapper import run_rest_transformation
from github2ocel.transform.graphql_mapper import process_issue_node

from github2ocel.extractor.github.commit_rest import fetch_commits_rest
from github2ocel.extractor.github.deployments import fetch_deployments
from github2ocel.extractor.github.issue_and_pr import fetch_github_data
from github2ocel.extractor.github.releases import fetch_releases
from github2ocel.extractor.github.workflow_run import fetch_workflow_runs
from github2ocel.extractor.github.branches import fetch_branches
# exceptions
from github2ocel.client.exceptions import (
    RateLimitError,
    RetryableError,
    GraphQLError,
    FatalError
)

from github2ocel.config.profiles import get_profile_vars

logger = get_logger(__name__)

# Returns True if successful, False if there were fatal errors.
def run_extractor(ctx: RepoContext, builder: OCELBuilder, repo_id: str) -> bool:
    """
    Orchestrates the extraction process:
    1. GraphQL Phase (Issues, PRs, Timeline)
    2. REST Phase (Commits, workflows, releases)
    """

    logger.info(f"--- Extractor Start: {ctx.owner}/{ctx.repo} ---")
    stats = {
        "commits": 0, "issues": 0, "runs": 0,
        "releases": 0, "deployments": 0, "branches": 0
    }
    try:
        client = GitHubClient.from_context(ctx)
    except Exception as e:
        logger.critical(f"Failed to initialize GitHubClient: {e}")
        return False

    success = True
    try:
        profile_vars = get_profile_vars("complete")
        user_configured_limit = client.graphql_per_page
        is_heavy = profile_vars.get("withReviews") or profile_vars.get("withTimeline")
        safety_cap = 20 if is_heavy else 50
        final_page_size = min(user_configured_limit, safety_cap)

        variables = {
                "owner": client.owner,
                "repo": client.repo,
                "pageSize": final_page_size,
                **profile_vars
            }

        # 1. GraphQL phase
        logger.info("Starting GraphQL extraction...")
        nodes = fetch_github_data(client, variables)
        count_graphql = 0

        for node in nodes:
            process_issue_node(node, builder, repo_id)
            count_graphql += 1

        stats["issues"] = count_graphql
        logger.info(f"GraphQL extraction completed ({count_graphql} nodes).")

    except (RateLimitError, RetryableError, GraphQLError) as e:
        logger.error(f"GraphQL Critical Failure: {e}")
        success = False

    except FatalError as e:
        logger.critical(f"GraphQL Fatal Error (Auth/Perms): {e}")
        client.close()
        success = False

    except Exception as e:
        logger.exception(f"Unexpected GraphQL failure: {e}")
        success = False

    if not success:
        logger.error("Skipping REST phase due to previous errors.")
        client.close()
        return stats, False

    # 2. REST phase
    try:
        logger.info("Starting REST extraction...")

        fetch_rest = {
            "commits": fetch_commits_rest(client, max_detailed_total=None),
            "runs": fetch_workflow_runs(client),
            "releases": fetch_releases(client),
            "deployments": fetch_deployments(client),
            "branches": fetch_branches(client)
        }

        processing_stats = run_rest_transformation(fetch_rest, builder, repo_id)
        stats.update(processing_stats)

        logger.info("REST extraction completed.")

    except (RateLimitError, RetryableError) as e:
        logger.error(f"REST Critical Failure: {e}")
        success = False
    except FatalError as e:
        logger.critical(f"REST Fatal Error: {e}")
        success = False
    except Exception as e:
        logger.exception(f"Unexpected REST failure: {e}")
        success = False
    finally:
        client.print_rate_limit_stats()
        client.close()

    return stats, success