from typing import Dict, Any
from shared.ocel.builder import OCELBuilder
from shared.ocel.model.models import ObjectInstance
from github2ocel.transform.utils.activity import Activities
from github2ocel.transform.utils.helper import make_id, safe_timestamp, create_event
from github2ocel.transform.utils.ensure import ensure_user, ensure_commit
from shared.logger import get_logger

logger = get_logger(__name__)

def process_release(release: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Map a GraphQL Release node to OCEL 2.0.

    Objects:   Release
    Events:    ReleaseCreated
    O2O:       Release → Repository (contained_in)
               Release → Author/User (created_by)
               Release → Tag         (tagged_as)      — if Tag object exists from Phase 0
               Release → Commit      (points_to_commit) — stub if needed
    """
    release_id_raw = release.get("id")
    if not release_id_raw:
        logger.warning("Skipping release without id")
        return

    rel_id   = make_id(repo_id, "release", release_id_raw)
    tag_name = release.get("tagName") or release.get("tag_name") or ""

    # Timestamps: prefer publishedAt, fall back to createdAt
    ts = safe_timestamp(
        release.get("publishedAt") or release.get("published_at"),
        fallback=release.get("createdAt") or release.get("created_at"),
    )

    # Asset aggregates
    assets_wrapper  = release.get("releaseAssets") or {}
    asset_nodes     = assets_wrapper.get("nodes") or []
    assets_count    = assets_wrapper.get("totalCount") or len(asset_nodes)
    total_downloads = sum(a.get("downloadCount") or 0 for a in asset_nodes)

    # Object: Release
    obj = ObjectInstance(object_id=rel_id, object_type="Release")
    obj.add_snapshot(
        time=ts,
        attributes={
            "tag_name":        tag_name,
            "name":            (release.get("name") or "")[:255],
            "description":     (release.get("description") or "")[:500],
            "url":             release.get("url") or "",
            "is_prerelease":   int(release.get("isPrerelease") or release.get("prerelease") or False),
            "is_draft":        int(release.get("isDraft") or False),
            "assets_count":    assets_count,
            "total_downloads": total_downloads,
            "updated_at":      safe_timestamp(release.get("updatedAt")),
        }
    )

    # O2O: Release → Repository
    obj.add_rel(repo_id, "contained_in")

    # O2O: Release → Author
    author_login = (release.get("author") or {}).get("login")
    author_id = ensure_user(builder, repo_id, author_login, timestamp=ts) if author_login else None
    if author_id:
        obj.add_rel(author_id, "created_by")

    # O2O: Release → Tag (Tag object exists from Phase 0 fetch_tags)
    # Tags are keyed by tag_name — direct resolution via make_id + object_registry (O(1), no SQL)
    if tag_name:
        tag_id = make_id(repo_id, "tag", tag_name)
        if builder.object_exists(tag_id):
            obj.add_rel(tag_id, "tagged_as")

    builder.insert_object(obj)

    # O2O: Release → Commit (resolve from tag target)
    commit_oid = _resolve_commit_oid(release.get("tag"))
    if commit_oid:
        commit_id = ensure_commit(builder, repo_id, commit_oid, timestamp=ts)
        if commit_id:
            proxy = ObjectInstance(object_id=rel_id, object_type="Release")
            proxy.add_rel(commit_id, "points_to_commit")
            builder.insert_object(proxy)

    # Event: ReleaseCreated
    create_event(
        builder=builder,
        event_type=Activities.RELEASE_CREATED,
        ts=ts,
        attributes={
            "tag":             tag_name,
            "is_prerelease":   int(release.get("isPrerelease") or release.get("prerelease") or False),
            "assets_count":    assets_count,
            "total_downloads": total_downloads,
            "source":          "graphql",
        },
        relationships=[
            (rel_id,    "subject"),
            (repo_id,   "context"),
            (author_id, "actor") if author_id else None,
        ]
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