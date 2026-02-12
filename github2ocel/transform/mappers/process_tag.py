import logging
import uuid
from typing import Dict, Any
from github2ocel.transform.builder import OCEL2Builder
from github2ocel.transform.utils.helper import make_id, safe_timestamp, parse_semver
from github2ocel.transform.utils.ensure import ensure_commit
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.model.models import ObjectInstance, Event

logger = logging.getLogger(__name__)

def process_tag(tag_node: Dict[str, Any], builder: OCEL2Builder, repo_id: str) -> None:
    """
    Mapea Tags de Git/GitHub a Objetos OCEL con SemVer.
    """
    tag_name = tag_node.get("name")
    if not tag_name: return

    # Semantic Analysis
    semver = parse_semver(tag_name)

    commit_sha = tag_node.get("commit", {}).get("sha")

    raw_date = tag_node.get("date") or tag_node.get("commit", {}).get("date")
    ts = safe_timestamp(raw_date)

    try:
        tag_id = make_id(repo_id, "tag", tag_name)
    except ValueError:
        return

    # Registrar Objeto Tag
    tag_obj = ObjectInstance(object_id=tag_id, object_type="Tag")

    tag_obj.add_snapshot(
        time=ts,
        attributes={
            "name": tag_name,
            "is_semver": semver["is_semver"],
            "major": semver["major"],
            "minor": semver["minor"],
            "patch": semver["patch"],
            "prerelease": semver["prerelease"]
        }
    )

    # Link Tag -> Repositorio
    tag_obj.add_rel(target_id=repo_id, qualifier="contained_in")

    # Link Tag -> Commit
    commit_id = None
    if commit_sha:
        commit_id = ensure_commit(builder, repo_id, commit_sha, timestamp=ts)
        if commit_id:
            tag_obj.add_rel(target_id=commit_id, qualifier="tags_commit")

    builder.insert_object(tag_obj)

    # Event: Tag Created
    try:
        change_type = "patch"
        if semver["is_semver"]:
            if semver["major"] > 0 and semver["minor"] == 0 and semver["patch"] == 0:
                change_type = "major"
            elif semver["minor"] > 0 and semver["patch"] == 0:
                change_type = "minor"

        evt = Event(
            event_id=str(uuid.uuid4()),
            event_type=Activities.TAG_CREATED,
            time=ts,
            attributes={
                "version": tag_name,
                "change_type": change_type,
                "source": "github_api"
            }
        )

        evt.add_rel(tag_id, "created_item")
        evt.add_rel(repo_id, "repository_context")
        if commit_id:
            evt.add_rel(commit_id, "tagged_commit")

        builder.insert_event(evt)

    except Exception as e:
        logger.error(f"Failed to record event for tag {tag_name}: {e}")