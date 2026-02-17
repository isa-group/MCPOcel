import logging
import uuid
from typing import Dict, Any

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.utils.helper import make_id, safe_timestamp
from github2ocel.transform.utils.ensure import ensure_user
from shared.ocel.model.models  import Event, ObjectInstance

logger = logging.getLogger(__name__)

def process_release(release: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Process a release from REST API with OCEL 2.0 compliance.
    """
    if not release.get("id"):
        logger.warning("Skipping release without ID")
        return

    # 1. Identity & Time
    try:
        rel_id = make_id(repo_id, "release", release["id"])
    except ValueError as e:
        logger.error(f"Failed to create release ID: {e}")
        return

    # Timestamp logic: Published > Created > Now (Fallback in safe_timestamp)
    ts = safe_timestamp(
        release.get("published_at"),
        fallback=release.get("created_at")
    )

    tag_name = release.get("tag_name", "unknown")

    # 2. Register Object
    rel_obj = ObjectInstance(object_id=rel_id, object_type="Release")
    rel_obj.add_snapshot(
        time=ts,
        attributes={
            "tag_name": tag_name,
            "name": release.get("name", "")[:255],
            "prerelease": int(release.get("prerelease", False))
        }
    )
    # Relación O2O: La release pertenece al repositorio
    rel_obj.add_rel(target_id=repo_id, qualifier="contained_in")

    builder.insert_object(rel_obj)

    # 3. Dependencies
    author_login = release.get("author", {}).get("login")
    author_id = ensure_user(builder, repo_id, author_login, timestamp=ts)

    # 4. Relationships
    rels = [
        {"objectId": rel_id, "qualifier": "released_item"},
        {"objectId": repo_id, "qualifier": "repository_context"}
    ]
    if author_id:
        rels.append({"objectId": author_id, "qualifier": "releaser"})

    # 5. Event
    try:
        evt = Event(
            event_id=str(uuid.uuid4()),
            event_type=Activities.RELEASE_CREATED,
            time=ts,
            attributes={
                "tag": tag_name,
                "source": "rest_api"
            }
        )
        evt.add_rel(rel_id, "released_item")
        evt.add_rel(repo_id, "repository_context")
        if author_id:
            evt.add_rel(author_id, "releaser")

        builder.insert_event(evt)
    except Exception as e:
        logger.error(f"Failed to create release event: {e}")