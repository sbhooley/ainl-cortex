"""Bump procedural pattern fitness after successful ``ainl_run``."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from .node_types import NodeType
except ImportError:
    from node_types import NodeType


def record_success(
    store,
    project_id: str,
    *,
    label: Optional[str] = None,
    adapters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    After a successful AINL run, reinforce procedural patterns for this project.

    Matches patterns whose ``pattern_name`` equals ``label`` (when provided) or
    whose ``tool_sequence`` overlaps enabled adapters. Uses EMA via
    ``PatternExtractor.update_pattern_fitness``.
    """
    try:
        from .extractor import PatternExtractor
    except ImportError:
        from extractor import PatternExtractor

    if store is None or not project_id:
        return {"ok": False, "updated": 0, "reason": "missing_store_or_project"}

    try:
        patterns = store.query_by_type(NodeType.PROCEDURAL, project_id, limit=100)
    except Exception as exc:
        return {"ok": False, "updated": 0, "error": str(exc)}

    if not patterns:
        return {"ok": True, "updated": 0, "reason": "no_patterns"}

    enabled = set()
    if adapters and isinstance(adapters.get("enable"), list):
        enabled = {str(x).lower() for x in adapters["enable"]}

    extractor = PatternExtractor()
    updated = 0
    for node in patterns:
        data = dict(node.data or {})
        name = str(data.get("pattern_name") or "")
        seq = [str(t).lower() for t in (data.get("tool_sequence") or [])]
        match = False
        if label and name and label.lower() in {name.lower(), name.lower().replace(" ", "_")}:
            match = True
        elif enabled and seq and enabled.intersection(seq):
            match = True
        elif not label and not enabled:
            match = True
        if not match:
            continue
        before = float(data.get("fitness", 0.5))
        extractor.update_pattern_fitness(data, success=True)
        node.data = data
        node.confidence = float(data.get("fitness", before))
        store.write_node(node)
        updated += 1

    return {"ok": True, "updated": updated, "project_id": project_id}
