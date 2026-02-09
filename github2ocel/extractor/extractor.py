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
# exceptions
from github2ocel.client.exceptions import (
    RateLimitError,
    RetryableError,
    GraphQLError,
    FatalError
)

logger = get_logger(__name__)

# Returns True if successful, False if there were fatal errors.
def run_extractor(ctx: RepoContext, builder: OCELBuilder, repo_id: str) -> bool:

    logger.info(f"--- Extractor Start: {ctx.owner}/{ctx.repo} ---")

    try:
        client = GitHubClient.from_context(ctx)
    except Exception as e:
        logger.critical(f"Failed to initialize GitHubClient: {e}")
        return False

    success = True

    # 1. GraphQL phase
    try:
        logger.info("Starting GraphQL extraction...")
        nodes = fetch_github_data(client)
        count_graphql = 0

        for node in nodes:
            process_issue_node(node, builder, repo_id)
            count_graphql += 1

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
        return False

    # 2. REST phase
    try:
        logger.info("Starting REST extraction...")

        commits = fetch_commits_rest(client, max_detailed_total=50)
        run_rest_transformation({"commits": commits}, builder, repo_id)

        workflow_runs = fetch_workflow_runs(client)
        run_rest_transformation({"runs": workflow_runs}, builder, repo_id)

        releases = fetch_releases(client)
        run_rest_transformation({"releases": releases}, builder, repo_id)

        deployments = fetch_deployments(client)
        run_rest_transformation({"deployments": deployments}, builder, repo_id)

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

    return success