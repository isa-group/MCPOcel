from typing import Dict, Any
from shared.ocel.builder import OCELBuilder
from shared.ocel.model.models import ObjectInstance
from github2ocel.transform.utils.helper import make_id
from github2ocel.transform.utils.ensure import ensure_file
from shared.logger import get_logger

logger = get_logger(__name__)


def process_commit_files(payload: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> tuple:
    """
    Add Commit -> File O2O links and enrich the Commit snapshot with
    REST-only verification detail.

    payload: from fetch_commit_files — { sha, files, verified, verification_reason, stats }
    Returns (links, new_files): O2O relationships added, new File objects created.
    """
    sha   = payload.get("sha")
    files = payload.get("files") or []

    if not sha:
        return 0, 0

    commit_id = make_id(repo_id, "commit", sha)
    if not builder.object_exists(commit_id):
        logger.debug(f"[process_commit_files] Commit {sha[:7]} not in builder — skipping")
        return 0, 0

    proxy = ObjectInstance(object_id=commit_id, object_type="Commit")

    # Enrich snapshot with REST-only fields (upserted onto existing object)
    stats = payload.get("stats") or {}
    proxy.add_snapshot(
        time=None,   # no new timestamp — just attribute enrichment
        attributes={
            "verification_reason": payload.get("verification_reason", ""),
            "diff_total":          stats.get("total", 0),
        }
    )

    linked = 0
    new_files = 0
    for f in files[:100]:  # hard cap — pathological monorepo commits
        path = f.get("path")
        if not path:
            continue

        status = f.get("status", "modified")
        existed = builder.object_exists(make_id(repo_id, "file", path))
        fid = ensure_file(builder, repo_id, path, timestamp=None)
        if not fid:
            continue
        if not existed:
            new_files += 1

        proxy.add_rel(fid, qualifier=f"modifies_file_{status}")
        linked += 1

        # For renames: also link the previous path so the old File object
        # gets a "renamed_to" rel, preserving continuity in process mining
        prev_path = f.get("previous_path")
        if status == "renamed" and prev_path:
            prev_existed = builder.object_exists(make_id(repo_id, "file", prev_path))
            prev_fid = ensure_file(builder, repo_id, prev_path, timestamp=None)
            if prev_fid:
                if not prev_existed:
                    new_files += 1
                proxy.add_rel(prev_fid, qualifier="modifies_file_renamed_from")
                linked += 1

    if linked or payload.get("verification_reason"):
        builder.insert_object(proxy)

    return linked, new_files