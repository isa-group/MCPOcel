from typing import Dict, Any

from shared.ocel.builder import OCELBuilder
from shared.ocel.model.models import ObjectInstance
from github2ocel.transform.utils.helper import make_id, safe_timestamp, parse_semver, create_event
from github2ocel.transform.utils.ensure import ensure_commit, ensure_tagger
from github2ocel.transform.utils.activity import Activities
from shared.logger import get_logger

logger = get_logger(__name__)


def process_tag(tag_node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Register a GitHub tag (lightweight or annotated) as an OCEL 2.0 object.

    Source: TAGS_QUERY (refs/tags/), normalized by fetch_tags into a flat dict.

    Lightweight tags point directly to a commit — their date is committedDate
    and tagger identity comes from the commit author.

    Annotated tags have their own metadata object — date is the tagger.date
    (when git tag -a was run) and the message is the tag annotation body.
    Note: annotated tag signatures are not exposed in this query fragment;
    is_signed is always 0 for annotated tags.

    SemVer change_type heuristic: detects "round" versions only
    (x.0.0 → major, x.y.0 → minor, otherwise patch). Non-SemVer tags
    always get change_type="other".
    """
    tag_name = tag_node.get("name")
    if not tag_name:
        return

    raw_id = tag_node.get("id") or tag_name
    tag_id = make_id(repo_id, "tag", raw_id)

    semver = parse_semver(tag_name)
    commit_sha = (tag_node.get("commit") or {}).get("sha") or ""
    ts = safe_timestamp(tag_node.get("date"), use_now=False)

    is_annotated = int(tag_node.get("is_annotated", 0))
    ci_state = tag_node.get("ci_state") or ""
    is_signed = int(tag_node.get("is_signed", 0))
    release_pr_count = int(tag_node.get("release_pr_count", 0))
    message = (tag_node.get("message") or "")[:500]

    # Object: Tag
    tag_obj = ObjectInstance(object_id=tag_id, object_type="Tag")
    tag_obj.add_snapshot(
        time=safe_timestamp(None), # unix epoch OCEL2.0 standard
        attributes={
            "name":             tag_name,
            "github_node_id":   raw_id if tag_node.get("id") else "",
            "is_annotated":     is_annotated,
            "message":          message,
            "is_semver":        semver["is_semver"],
            "major":            semver["major"],
            "minor":            semver["minor"],
            "patch":            semver["patch"],
            "prerelease":       semver["prerelease"] or "",
            "ci_state":         ci_state,
            "is_signed":        is_signed,
            "release_pr_count": release_pr_count,
        }
    )

    # O2O: Tag -> Repository
    tag_obj.add_rel(repo_id, "contained_in")

    # O2O: Tag -> Commit (stub — Phase 4 enriches with full commit data)
    commit_id = None
    if commit_sha:
        commit_id = ensure_commit(builder, repo_id, commit_sha, timestamp=ts)
        if commit_id:
            tag_obj.add_rel(commit_id, "tags_commit")

    # O2O: Tag -> Tagger (GitHub login preferred, git identity as fallback)
    tagger_info = tag_node.get("tagger")
    tagger_id   = ensure_tagger(builder, repo_id, tagger_info, timestamp=ts)
    if tagger_id:
        tag_obj.add_rel(tagger_id, "created_by")

    builder.insert_object(tag_obj)

    # Determine semantic change type
    change_type = _classify_semver_change(semver)

    rels = [
        (tag_id,  "created_item"),
        (repo_id, "repository_context"),
    ]
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
            "is_annotated": is_annotated,
            "is_semver":    semver["is_semver"],
            "message":      message,
            "source":       "graphql",
        },
        relationships=rels,
    )


def _classify_semver_change(semver: Dict[str, Any]) -> str:
    """
    Heuristic: classifies a SemVer tag as major / minor / patch / other.
    Detects 'round' version bumps only (x.0.0, x.y.0).
    Non-SemVer tags always return 'other'.
    """
    if not semver["is_semver"]:
        return "other"
    if semver["minor"] == 0 and semver["patch"] == 0:
        return "major"
    if semver["patch"] == 0:
        return "minor"
    return "patch"