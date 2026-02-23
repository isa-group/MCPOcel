# github2ocel/transform/graphql_mapper.py (o donde prefieras ubicar este enrutador)

from typing import Dict, Any
from shared.ocel.builder import OCELBuilder
from github2ocel.utils.get_node_type import get_node_type
from github2ocel.transform.graphql_mapper import process_issue_node
from github2ocel.transform.mappers.process_discussion_graphql import process_discussion_node 
from shared.logger import get_logger

logger = get_logger(__name__)

def process_graphql_node(node: Dict[str, Any], builder: OCELBuilder, repo_id: str) -> None:
    """
    Main route for mapping GraphQL nodes to OCEL objects and events.
    Acts as a "traffic light" that directs traffic.
    """
    try:
        node_type = get_node_type(node)
        
        if node_type == "Issue":
            process_issue_node(node, builder, repo_id, node_type="Issue")
        elif node_type == "PullRequest":
            # Reuse current logic for PRs, as process_issue_node handles both
            process_issue_node(node, builder, repo_id, node_type="PullRequest")
        elif node_type == "Discussion":
            process_discussion_node(node, builder, repo_id)
            
    except ValueError as e:
        logger.error(f"Skipping node: {e}")