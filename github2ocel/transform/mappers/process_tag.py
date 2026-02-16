import logging
import uuid
from typing import Dict, Any
from github2ocel.transform.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, safe_timestamp, parse_semver
from github2ocel.transform.utils.ensure import ensure_commit, ensure_user
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.model.models import ObjectInstance, Event

logger = logging.getLogger(__name__)

def process_tag(tag_node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Mapea Tags de Git/GitHub a Objetos OCEL con SemVer.
    """
    tag_name = tag_node.get("name")
    if not tag_name: return

    # Semantic Analysis
    semver = parse_semver(tag_name)

    commit_data = tag_node.get("commit", {})
    commit_sha = commit_data.get("sha") or commit_data.get("oid")
    raw_date = tag_node.get("date")

    if not raw_date and commit_sha:
         pass

    ts = safe_timestamp(raw_date)

    try:
        tag_id = make_id(repo_id, "tag", tag_name)
    except ValueError:
        return

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

    # Link Tag -> Repository
    tag_obj.add_rel(target_id=repo_id, qualifier="contained_in")

    # Relationship: Tag -> Commit (O2O)
    commit_id = None
    if commit_sha:
        commit_id = ensure_commit(builder, repo_id, commit_sha, timestamp=ts)
        if commit_id:
            tag_obj.add_rel(target_id=commit_id, qualifier="tags_commit")

    # Link Tag -> Commit
    commit_id = None
    if commit_sha:
        commit_id = ensure_commit(builder, repo_id, commit_sha, timestamp=ts)
        if commit_id:
            tag_obj.add_rel(target_id=commit_id, qualifier="tags_commit")

    builder.insert_object(tag_obj)

    # Relationship: Tag -> Tagger (User)
    tagger_info = tag_node.get("tagger")
    tagger_id = None
    if tagger_info and tagger_info.get("login"):
        tagger_id = ensure_user(builder, repo_id, tagger_info["login"], timestamp=ts)
        if tagger_id:
             tag_obj.add_rel(target_id=tagger_id, qualifier="created_by")

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

        if tagger_id:
            evt.add_rel(tagger_id, "actor")

        builder.insert_event(evt)

    except Exception as e:
        logger.error(f"Failed to record event for tag {tag_name}: {e}")