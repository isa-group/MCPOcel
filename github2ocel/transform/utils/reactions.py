"""
Reaction utilities for GitHub reactionGroups.

GitHub currently supports 8 reaction types. If GitHub adds new ones,
add them here — no mapper needs to change.

Usage:
    attrs = parse_reaction_groups(node.get("reactionGroups", []))
    # Returns a flat dict ready to unpack into an OCEL snapshot:
    # {
    #   "reactions_thumbs_up": 3,
    #   "reactions_thumbs_down": 0,
    #   "reactions_laugh": 1,
    #   ...
    #   "reactions_positive": 4,
    #   "reactions_negative": 0,
    # }
"""

from typing import Any, Dict, List

# All known GitHub reaction content values → OCEL attribute name.
# Add new entries here when GitHub expands the set.
_REACTION_MAP: Dict[str, str] = {
    "THUMBS_UP":   "reactions_thumbs_up",
    "THUMBS_DOWN": "reactions_thumbs_down",
    "LAUGH":       "reactions_laugh",
    "HOORAY":      "reactions_hooray",
    "CONFUSED":    "reactions_confused",
    "HEART":       "reactions_heart",
    "ROCKET":      "reactions_rocket",
    "EYES":        "reactions_eyes",
}

# Sentiment groupings — drives reactions_positive / reactions_negative aggregates.
# Unknown reaction types are counted as positive (non-negative) by default.
_NEGATIVE: frozenset = frozenset({"THUMBS_DOWN", "CONFUSED"})


def parse_reaction_groups(
    reaction_groups: List[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Parse a GitHub `reactionGroups` node list into a flat attribute dict.

    Args:
        reaction_groups: value of node.get("reactionGroups", []) from any
                         GitHub GraphQL query that includes:
                             reactionGroups {
                               content
                               reactors(first: 0) { totalCount }
                             }

    Returns:
        Flat dict with one key per known reaction type plus aggregate keys:
            reactions_thumbs_up, reactions_thumbs_down, reactions_laugh,
            reactions_hooray, reactions_confused, reactions_heart,
            reactions_rocket, reactions_eyes,
            reactions_positive, reactions_negative
        All values default to 0. Unknown reaction types from the API are
        accumulated separately in reactions_unknown (only present when > 0)
        and excluded from reactions_positive / reactions_negative aggregates.
    """
    counts: Dict[str, int] = {attr: 0 for attr in _REACTION_MAP.values()}
    positive = 0
    negative = 0
    unknown = 0

    for group in (reaction_groups or []):
        content = group.get("content", "")
        count = (group.get("reactors") or {}).get("totalCount", 0)

        if count == 0:
            continue

        attr = _REACTION_MAP.get(content)
        if attr:
            counts[attr] += count

            if content in _NEGATIVE:
                negative += count
            else:
                positive += count
        else:
            unknown += count

    counts["reactions_positive"] = positive
    counts["reactions_negative"] = negative

    if unknown:
        counts["reactions_unknown"] = unknown

    return counts
