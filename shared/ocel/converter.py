"""OCEL format converter.

Converts between PM4PY OCEL objects and OCEL 2.0 dict format.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


def ocel_to_dict(ocel_data, config) -> Dict[str, Any]:
    """
    Convert PM4PY OCEL object to dict format for indexing.
    
    Args:
        ocel_data: Loaded OCEL data (PM4PY or dict format).
        config: OCEL configuration with attribute names and object types.
        
    Returns:
        Dict conforming to OCEL 2.0 JSON schema.
    """
    result: Dict[str, Any] = {
        "eventTypes": [{"name": et} for et in config.event_types],
        "objectTypes": [{"name": ot} for ot in config.object_types],
        "events": [],
        "objects": [],
    }
    
    try:
        if hasattr(ocel_data, "events"):
            # PM4Py format - extract from DataFrames
            events_df = ocel_data.events
            for _, row in events_df.iterrows():
                event = {
                    "id": str(row.get("ocel:eid", "")),
                    "type": str(row.get("ocel:activity", "")),
                    "time": str(row.get("ocel:timestamp", "")),
                    "attributes": [],
                    "relationships": [],
                }
                result["events"].append(event)
        
        if hasattr(ocel_data, "objects"):
            objects_df = ocel_data.objects
            for _, row in objects_df.iterrows():
                obj = {
                    "id": str(row.get("ocel:oid", "")),
                    "type": str(row.get("ocel:type", "")),
                    "attributes": [],
                    "relationships": [],
                }
                result["objects"].append(obj)
    except Exception as e:
        logger.warning(f"Error converting OCEL to dict: {e}")
    
    return result
