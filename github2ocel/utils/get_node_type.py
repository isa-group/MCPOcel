from typing import Any, Dict

# Types explicitly supported
SUPPORTED_NODE_TYPES = {
    "Issue",
    "PullRequest",
    "Discussion",
}

def get_node_type(node: Dict[str, Any]) -> str:
    """
    Resolves the semantic type of a GitHub GraphQL node.
    Prefers __typename, falls back to structural heuristics.
    """
    # Use the exact type returned by GraphQL
    typename = node.get("__typename")
    if typename in SUPPORTED_NODE_TYPES:
        return typename
    
    # Pull Request
    if "mergedAt" in node or "isDraft" in node:
        return "PullRequest"

    # Discussion
    # Note: answerChosenAt can be None in Python if it is null in GraphQL, 
    # but the key will exist in the dictionary, so the “in” operator works.
    if "category" in node and "answerChosenAt" in node:
        return "Discussion"

    # Issue
    if "state" in node and "number" in node:
        return "Issue"

    # If the node does not match anything known, we abort
    raise ValueError(f"Unsupported or unknown node type. Keys found: {list(node.keys())}")