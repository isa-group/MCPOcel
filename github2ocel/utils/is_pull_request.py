from typing import Any, Dict

def _get_node_type(node: Dict[str, Any]) -> str:
    node_type = node.get("__type")
    if node_type not in {"Issue", "PullRequest"}:
        # Fallback in case the GraphQL query did not return __type
        if "pullRequest" in node or "mergedAt" in node: return "PullRequest"
        if "state" in node: return "Issue" # Generic fallback
        raise ValueError(f"Nodo inválido o tipo no soportado: {node}")
    return node_type

def is_pull_request(node: Dict[str, Any]) -> bool:
    return _get_node_type(node) == "PullRequest"