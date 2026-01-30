from typing import Optional, Dict, Any
import uuid

from github2ocel.transform.builder import OCELBuilder
from .helper import make_id, parse_commit_message, safe_timestamp

def make_id(*parts: Any) -> str:
    """
    Generate deterministic OCEL object IDs.
    Replaces spaces, slashes, and colons with underscores.
    Ignores None or empty parts.
    Raises ValueError if no valid parts provided.
    """
    valid_parts = [
        str(p).replace(" ", "_").replace("/", "_").replace(":", "")
        for p in parts if p is not None and str(p).strip() != ""
    ]

    if not valid_parts:
        raise ValueError(f"Cannot create ID from empty parts: {parts}")

    return "_".join(valid_parts)

# Object Ensurers with existence checks
def ensure_user(builder: OCELBuilder, login: Optional[str]) -> Optional[str]:
    """Ensure user object exists. Returns None if login is invalid."""
    if not login or not isinstance(login, str):
        return None

    user_id = make_id("user", login)

    # Only create if doesn't exist
    if user_id not in builder.data.get("ocel:objects", {}):
        builder.add_object(user_id, "User", {"login": login})

    return user_id


def ensure_file(builder: OCELBuilder, repo_id: str, path: str) -> Optional[str]:
    """Ensure file object exists. Returns None if path is invalid."""
    if not path or not isinstance(path, str):
        return None

    file_id = make_id(repo_id, "file", path)

    if file_id not in builder.data.get("ocel:objects", {}):
        builder.add_object(file_id, "File", {"path": path})

    return file_id


def ensure_label(builder: OCELBuilder, repo_id: str, label: Dict[str, Any]) -> Optional[str]:
    """Ensure label object exists. Returns None if label data is invalid."""
    if not label or not label.get("name"):
        return None

    label_id = make_id(repo_id, "label", label["name"].lower())

    if label_id not in builder.data.get("ocel:objects", {}):
        builder.add_object(label_id, "Label", {
            "name": label["name"],
            "color": label.get("color", "")
        })

    return label_id


def ensure_comment(builder: OCELBuilder, repo_id: str, comment: Dict[str, Any]) -> Optional[str]:
    """Ensure comment object exists. Returns None if comment data is invalid."""
    if not comment:
        return None

    comment_id = make_id(
        repo_id,
        "comment",
        comment.get("id", uuid.uuid4().hex[:8])
    )
    created_at = safe_timestamp(comment.get("createdAt"))
    updated_at = safe_timestamp(comment.get("lastEditedAt"), fallback=created_at)

    if comment_id not in builder.data.get("ocel:objects", {}):
        builder.add_object(comment_id, "Comment", {
            "body": comment.get("body", ""),
            "created_at": created_at,
            "updated_at": updated_at or created_at,
            "status": "created"
        })

    return comment_id

def ensure_commit(builder: OCELBuilder, repo_id: str, sha: str,
                  message: str = "", source: str = "rest") -> Optional[str]:
    """
    Ensure commit object exists.
    Returns None if sha is invalid.
    """
    if not sha or not isinstance(sha, str):
        return None

    commit_id = make_id(repo_id, "commit", sha)

    # Only create if doesn't exist
    if commit_id not in builder.data.get("ocel:objects", {}):
        attrs = {"sha": sha, "source": source}
        if message:
            attrs.update(parse_commit_message(message))
        builder.add_object(commit_id, "Commit", attrs)

    return commit_id
