from typing import Dict, Any
from shared.ocel.builder import OCELBuilder
from shared.ocel.model.models import ObjectInstance
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user, ensure_commit
from shared.logger import get_logger

logger = get_logger(__name__)

def process_release(release: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    release_id_raw = release.get("id")
    release_db_id  = release.get("databaseId")
    if not release_id_raw and not release_db_id:
        logger.warning("Skipping release without id")
        return

    rel_id = make_id(repo_id, "release", release_db_id or release_id_raw)

    tag_name = release.get("tagName") or ""
    created_ts = safe_timestamp(release.get("createdAt"))
    published_ts = safe_timestamp(release.get("publishedAt")) if release.get("publishedAt") else None
    is_draft = int(release.get("isDraft") or False)
    is_prerelease = int(release.get("isPrerelease") or False)

    # Snapshot at published time if available, created time otherwise
    obj_ts = published_ts or created_ts

    assets_wrapper  = release.get("releaseAssets") or {}
    asset_nodes     = assets_wrapper.get("nodes") or []
    assets_count    = assets_wrapper.get("totalCount") or len(asset_nodes)
    total_downloads = sum(a.get("downloadCount") or 0 for a in asset_nodes)

    author_login = (release.get("author") or {}).get("login")
    author_id = ensure_user(builder, repo_id, author_login, timestamp=obj_ts) if author_login else None

    # O2O: Release → Tag
    tag_id = None
    if tag_name:
        candidate = make_id(repo_id, "tag", tag_name)
        if builder.object_exists(candidate):
            tag_id = candidate

    # O2O: Release → Commit
    commit_id = None
    commit_oid = _resolve_commit_oid(release.get("tag"))
    if commit_oid:
        commit_id = ensure_commit(builder, repo_id, commit_oid, timestamp=obj_ts)

    # Object: Release
    obj = ObjectInstance(object_id=rel_id, object_type="Release")
    obj.add_snapshot(
        time=obj_ts,
        attributes={
            "github_node_id":  release_id_raw or "",
            "database_id":     release_db_id or 0,
            "tag_name":        tag_name,
            "name":            (release.get("name") or "")[:255],
            "description":     (release.get("description") or "")[:500],
            "url":             release.get("url") or "",
            "is_prerelease":   is_prerelease,
            "is_draft":        is_draft,
            "assets_count":    assets_count,
            "total_downloads": total_downloads,
            "updated_at":      safe_timestamp(release.get("updatedAt")),
        }
    )
    obj.add_rel(repo_id, "contained_in")
    if author_id:
        obj.add_rel(author_id, "created_by")
    if tag_id:
        obj.add_rel(tag_id, "tagged_as")
    if commit_id:
        obj.add_rel(commit_id, "points_to_commit")

    builder.insert_object(obj)  # una sola vez, con todas las rels ya resueltas

    # Base relationships for events — built once, reused
    base_rels = [(rel_id, "subject"), (repo_id, "context")]
    if author_id:
        base_rels.append((author_id, "actor"))
    if commit_id:
        base_rels.append((commit_id, "release_commit"))
    if tag_id:
        base_rels.append((tag_id, "release_tag"))

    # Event A: ReleaseCreated — when the release was first registered (createdAt)
    # For drafts this is when drafting began; for direct publishes it equals publishedAt.
    create_event(
        builder=builder,
        event_type=Activities.RELEASE_CREATED,
        ts=created_ts,
        attributes={
            "tag":           tag_name,
            "is_prerelease": is_prerelease,
            "is_draft":      is_draft,
            "source":        "graphql",
        },
        relationships=base_rels,
    )

    # Event B: ReleasePublished — only when publishedAt differs from createdAt
    # (draft was published later, or GitHub set them independently)
    if published_ts and published_ts != created_ts:
        create_event(
            builder=builder,
            event_type=Activities.RELEASE_PUBLISHED,  # needs adding to activity.py
            ts=published_ts,
            attributes={
                "tag":             tag_name,
                "is_prerelease":   is_prerelease,
                "assets_count":    assets_count,
                "total_downloads": total_downloads,
                "source":          "graphql",
            },
            relationships=base_rels,
        )

def _resolve_commit_oid(tag_field: Dict) -> str:
    """
    Extract the commit OID from the tag.target field.
    Handles both lightweight tags (→ Commit directly)
    and annotated tags (→ Tag → Commit).
    """
    if not tag_field:
        return None
    target = tag_field.get("target") or {}
    typename = target.get("__typename", "")

    if typename == "Commit":
        return target.get("oid")

    if typename == "Tag":
        # Annotated tag: target.target is the Commit
        inner = target.get("target") or {}
        return inner.get("oid")

    return None