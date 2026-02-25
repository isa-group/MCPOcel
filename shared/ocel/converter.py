"""OCEL format converter.

Converts between PM4PY OCEL objects and OCEL 2.0 dict format.
Uses only PM4PY's public API.
"""

import logging
import math
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# PM4PY internal column prefixes — not user-defined attributes
_OCEL_PREFIX = "ocel:"


def _is_attribute_column(col: str) -> bool:
    """Check if a column name is a user-defined attribute (not an OCEL internal column)."""
    return not col.startswith(_OCEL_PREFIX)


def _is_valid_value(val: Any) -> bool:
    """Check if a value is non-null and non-NaN.

    Handles float NaN via ``math.isnan`` and pandas/numpy sentinel
    values (``NaT``, ``NA``) via the ``val != val`` identity trick,
    without requiring a direct pandas import.
    """
    if val is None:
        return False
    if isinstance(val, float) and math.isnan(val):
        return False
    try:
        # NaN != NaN and NaT != NaT both evaluate to True
        if val != val:
            return False
    except (TypeError, ValueError):
        return False
    return True


def _dataframe_to_records(df) -> List[Dict[str, Any]]:
    """Convert a PM4PY internal DataFrame to a list of plain dicts.

    Uses the DataFrame's own ``to_dict`` method so that downstream
    code only works with standard Python dicts.
    """
    if df is None:
        return []
    try:
        return df.to_dict("records")
    except Exception:
        return []


def _extract_attributes(record: Dict[str, Any]) -> List[Dict[str, str]]:
    """Extract user-defined attributes from a record dict.

    Iterates over keys that are not PM4PY internal (``ocel:*``) and
    returns ``[{"name": col, "value": str(val)}, ...]`` for non-null values.
    """
    attrs: List[Dict[str, str]] = []
    for col, val in record.items():
        if _is_attribute_column(col) and _is_valid_value(val):
            attrs.append({"name": col, "value": str(val)})
    return attrs


def _build_event_types_with_attributes(config) -> List[Dict[str, Any]]:
    """Build eventTypes list including attribute definitions from config."""
    event_types: List[Dict[str, Any]] = []
    for et in config.event_types:
        et_dict: Dict[str, Any] = {"name": et}
        attr_names = config.attribute_names.get(et, [])
        if attr_names:
            et_dict["attributes"] = [{"name": a} for a in attr_names]
        event_types.append(et_dict)
    return event_types


def _build_object_types_with_attributes(config) -> List[Dict[str, Any]]:
    """Build objectTypes list including attribute definitions from config."""
    object_types: List[Dict[str, Any]] = []
    for ot in config.object_types:
        ot_dict: Dict[str, Any] = {"name": ot}
        attr_names = config.attribute_names.get(ot, [])
        if attr_names:
            ot_dict["attributes"] = [{"name": a} for a in attr_names]
        object_types.append(ot_dict)
    return object_types


def ocel_to_dict(ocel_data, config) -> Dict[str, Any]:
    """
    Convert PM4PY OCEL object to dict format for indexing.

    Extracts events, objects, their attributes (all non-``ocel:`` columns)
    and relationships from the PM4PY DataFrames so that downstream
    indexing/retrieval has access to the full OCEL content.

    Args:
        ocel_data: Loaded OCEL data (PM4PY or dict format).
        config: OCEL configuration with attribute names and object types.

    Returns:
        Dict conforming to OCEL 2.0 JSON schema, including attribute
        values and relationships.
    """
    result: Dict[str, Any] = {
        "eventTypes": _build_event_types_with_attributes(config),
        "objectTypes": _build_object_types_with_attributes(config),
        "events": [],
        "objects": [],
    }

    try:
        # ----------------------------------------------------------
        # Build a relations lookup for fast per-event access
        # ----------------------------------------------------------
        event_rels: Dict[str, List[Dict[str, str]]] = {}
        if hasattr(ocel_data, "relations") and ocel_data.relations is not None:
            for rec in _dataframe_to_records(ocel_data.relations):
                eid = str(rec.get("ocel:eid", ""))
                obj_id = str(rec.get("ocel:oid", ""))
                qualifier = str(rec.get("ocel:qualifier", "")) if _is_valid_value(rec.get("ocel:qualifier")) else "related"
                event_rels.setdefault(eid, []).append(
                    {"objectId": obj_id, "qualifier": qualifier}
                )

        # ----------------------------------------------------------
        # Events
        # ----------------------------------------------------------
        if hasattr(ocel_data, "events") and ocel_data.events is not None:
            for rec in _dataframe_to_records(ocel_data.events):
                eid = str(rec.get("ocel:eid", ""))
                event = {
                    "id": eid,
                    "type": str(rec.get("ocel:activity", "")),
                    "time": str(rec.get("ocel:timestamp", "")),
                    "attributes": _extract_attributes(rec),
                    "relationships": event_rels.get(eid, []),
                }
                result["events"].append(event)

        # ----------------------------------------------------------
        # Object-to-object relations lookup
        # ----------------------------------------------------------
        obj_rels: Dict[str, List[Dict[str, str]]] = {}
        if hasattr(ocel_data, "o2o") and ocel_data.o2o is not None:
            for rec in _dataframe_to_records(ocel_data.o2o):
                src = str(rec.get("ocel:oid", ""))
                tgt = str(rec.get("ocel:oid_2", rec.get("ocel:oid:2", "")))
                qualifier = str(rec.get("ocel:qualifier", "")) if _is_valid_value(rec.get("ocel:qualifier")) else "related"
                obj_rels.setdefault(src, []).append(
                    {"objectId": tgt, "qualifier": qualifier}
                )

        # ----------------------------------------------------------
        # Objects
        # ----------------------------------------------------------
        if hasattr(ocel_data, "objects") and ocel_data.objects is not None:
            for rec in _dataframe_to_records(ocel_data.objects):
                oid = str(rec.get("ocel:oid", ""))
                obj = {
                    "id": oid,
                    "type": str(rec.get("ocel:type", "")),
                    "attributes": _extract_attributes(rec),
                    "relationships": obj_rels.get(oid, []),
                }
                result["objects"].append(obj)
    except Exception as e:
        logger.warning(f"Error converting OCEL to dict: {e}")

    return result
