import logging
from datetime import datetime
from typing import Dict, Any

from github2ocel.transform.builder import OCELBuilder
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.utils.helper import make_id
from github2ocel.transform.utils.ensure import ensure_user, ensure_deployment, ensure_commit

logger = logging.getLogger(__name__)

# Release Mapper
def process_release(release: Dict[str, Any], builder: OCELBuilder,
                   repo_id: str) -> None:
    """
    Process a release from REST API.
    Validates required fields.
    """
    if not release.get("id"):
        logger.warning("Skipping release without ID")
        return
    tag_name = release.get("tag_name", "unknown")
    try:
        rel_id = make_id(repo_id, "release", release["id"])
    except ValueError as e:
        logger.error(f"Failed to create release ID: {e}")
        return

    builder.add_object(rel_id, "Release", {
        "tag_name": tag_name,
        "name": release.get("name", ""),
        "prerelease": bool(release.get("prerelease", False))
    })

    author_id = ensure_user(builder, release.get("author", {}).get("login"))

    rels = [
        builder.rel(rel_id, "target"),
        builder.rel(repo_id, "source")
    ]
    if author_id:
        rels.append(builder.rel(author_id, "author"))

    published_at = release.get("published_at") or release.get("created_at")


    if not published_at:
        logger.warning(f"Release {tag_name} (ID: {release['id']}) missing timestamp, using current time")
        published_at = datetime.now().isoformat() + "Z"

    try:
        builder.add_event(
            Activities.RELEASE_CREATED,
            published_at,
            rels,
            {"tag": tag_name}
        )
    except Exception as e:
        logger.error(f"Failed to create release event: {e}")



def process_deployment(
    deployment: Dict[str, Any],
    builder: OCELBuilder,
    repo_id: str
) -> None:
    """Process a deployment from REST API."""
    if not deployment.get("id"):
        logger.warning("Skipping deployment without ID")
        return

    try:
        deployment_id = make_id(repo_id, "deployment", deployment["id"])
    except ValueError as e:
        logger.error(f"Failed to create deployment ID: {e}")
        return

    dep_id = ensure_deployment(builder, repo_id, deployment)
    if not dep_id:
        return

    # Ensure related commit
    sha = deployment.get("sha")
    commit_id = None
    if sha:
        commit_id = ensure_commit(builder, repo_id, sha)
        if commit_id:
            builder.add_object_relationship(dep_id, commit_id, "deploys")

    creator_id = ensure_user(builder, deployment.get("creator", {}).get("login"))

    rels = [
        builder.rel(dep_id, "deployment"),
        builder.rel(repo_id, "repository")
    ]

    if commit_id:
        rels.append(builder.rel(commit_id, "commit"))

    if creator_id:
        rels.append(builder.rel(creator_id, "creator"))

    # Deployment Created Event
    created_at = deployment.get("created_at")
    if created_at:
        try:
            builder.add_event(
                Activities.DEPLOYMENT_CREATED,
                created_at,
                rels,
                {
                    "environment": deployment.get("environment", "unknown"),
                    "ref": deployment.get("ref", "")
                }
            )
        except Exception as e:
            logger.error(f"Failed to create deployment created event: {e}")

    # Process deployment statuses
    statuses = deployment.get("statuses", [])

    if statuses:
        latest_status = statuses[0]
        state = latest_status.get("state", "pending")
        updated_at = latest_status.get("updated_at") or latest_status.get("created_at")

        if not updated_at:
            return

        activity_map = {
            "success": Activities.DEPLOYMENT_SUCCEEDED,
            "failure": Activities.DEPLOYMENT_FAILED,
            "error": Activities.DEPLOYMENT_ERROR
        }

        activity = activity_map.get(state)

        if activity:
            try:
                builder.add_event(
                    activity,
                    updated_at,
                    rels,
                    {
                        "state": state,
                        "environment": deployment.get("environment", "unknown")
                    }
                )
            except Exception as e:
                logger.error(f"Failed to create deployment status event: {e}")