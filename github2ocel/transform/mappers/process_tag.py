import logging
from typing import Dict, Any, Optional

from shared.ocel.builder import OCELBuilder
from github2ocel.transform.utils.helper import make_id, safe_timestamp, parse_semver, create_event
from github2ocel.transform.utils.ensure import ensure_commit, ensure_tagger
from github2ocel.transform.utils.activity import Activities
from shared.ocel.model.models import ObjectInstance

logger = logging.getLogger(__name__)


def process_tag(tag_node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Maps GitHub tags (lightweight and annotated) to OCEL 2.0 objects.
    """
    tag_name = tag_node.get("name")
    if not tag_name:
        return

    # Use stable GraphQL id as raw_id when available, fallback to name
    raw_id = tag_node.get("id") or tag_name
    tag_id = make_id(repo_id, "tag", raw_id)

    semver     = parse_semver(tag_name)
    commit_sha = (tag_node.get("commit") or {}).get("sha")
    raw_date   = tag_node.get("date")
    ts         = safe_timestamp(raw_date, use_now=False)

    # If tag has no date, try to fall back to commit date (populated in Phase 4)
    # For now use epoch sentinel — acceptable since Phase 4 will enrich the commit
    tag_obj = ObjectInstance(object_id=tag_id, object_type="Tag")
    tag_obj.add_snapshot(
        time=ts,
        attributes={
            "name":         tag_name,
            "is_annotated": tag_node.get("is_annotated", 0),
            "message":      (tag_node.get("message") or "")[:500],
            "is_semver":    semver["is_semver"],
            "major":        semver["major"],
            "minor":        semver["minor"],
            "patch":        semver["patch"],
            "prerelease":   semver["prerelease"],
        }
    )

    # O2O: Tag -> Repository
    tag_obj.add_rel(target_id=repo_id, qualifier="contained_in")

    # O2O: Tag -> Commit (stub — Phase 4 enriches)
    commit_id = None
    if commit_sha:
        commit_id = ensure_commit(builder, repo_id, commit_sha, timestamp=ts)
        if commit_id:
            tag_obj.add_rel(target_id=commit_id, qualifier="tags_commit")

    # O2O: Tag -> Tagger (login or git identity fallback)
    tagger_info = tag_node.get("tagger")
    tagger_id   = ensure_tagger(builder, repo_id, tagger_info, timestamp=ts)
    if tagger_id:
        tag_obj.add_rel(target_id=tagger_id, qualifier="created_by")

    builder.insert_object(tag_obj)

    # Determine semantic change type for the event attribute
    change_type = "patch"
    if semver["is_semver"]:
        if semver["major"] > 0 and semver["minor"] == 0 and semver["patch"] == 0:
            change_type = "major"
        elif semver["minor"] > 0 and semver["patch"] == 0:
            change_type = "minor"

    # Build relationships explicitly
    rels = [(tag_id, "created_item"), (repo_id, "repository_context")]
    if commit_id:
        rels.append((commit_id, "tagged_commit"))
    if tagger_id:
        rels.append((tagger_id, "actor"))

    create_event(
        builder=builder,
        event_type=Activities.TAG_CREATED,
        ts=ts,
        attributes={
            "version":      tag_name,
            "change_type":  change_type,
            "is_annotated": tag_node.get("is_annotated", 0),
            "message":      (tag_node.get("message") or "")[:500],
            "source":       "graphql",
        },
        relationships=rels,
    )