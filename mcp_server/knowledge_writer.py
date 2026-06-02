"""
Backend-aware writer for content-knowledge semantic facts.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    from .knowledge_config import (
        artifact_cfg,
        default_topic_cluster,
        get_knowledge_capture_block,
    )
    from .node_types import (
        EdgeType,
        NodeType,
        create_edge,
        create_semantic_node,
        normalize_fact_text,
        semantic_content_id,
    )
except ImportError:
    from knowledge_config import (
        artifact_cfg,
        default_topic_cluster,
        get_knowledge_capture_block,
    )
    from node_types import (
        EdgeType,
        NodeType,
        create_edge,
        create_semantic_node,
        normalize_fact_text,
        semantic_content_id,
    )

logger = logging.getLogger(__name__)


def graph_db_path(project_id: str) -> Path:
    return (
        Path.home()
        / ".claude"
        / "projects"
        / project_id
        / "graph_memory"
        / "ainl_memory.db"
    )


def open_store(project_id: str):
    try:
        from .graph_store import get_graph_store
    except ImportError:
        from graph_store import get_graph_store

    db = graph_db_path(project_id)
    db.parent.mkdir(parents=True, exist_ok=True)
    return get_graph_store(db)


def _cap_fact(fact: str, max_chars: int) -> str:
    fact = normalize_fact_text(fact)
    if len(fact) <= max_chars:
        return fact
    return fact[: max_chars - 3].rstrip() + "..."


def ingest_facts(
    project_id: str,
    facts: Sequence[str],
    *,
    source_kind: str,
    source_ref: str = "",
    tags: Optional[List[str]] = None,
    topic_cluster: Optional[str] = None,
    source_turn_id: Optional[str] = None,
    episode_node_id: Optional[str] = None,
    confidence: float = 0.85,
    store=None,
) -> Dict[str, Any]:
    """
    Write semantic facts with deterministic IDs and optional DERIVES_FROM edge.

    Returns counts: written, skipped_empty, skipped_duplicate_bump.
    """
    cfg = artifact_cfg()
    max_facts = int(cfg.get("max_facts_per_artifact", 40))
    max_fact_chars = int(cfg.get("max_fact_chars", 400))
    min_conf = float(cfg.get("min_confidence", 0.55))
    confidence = max(min_conf, min(confidence, 1.0))

    cluster = topic_cluster or default_topic_cluster(project_id)
    base_tags = ["knowledge"]
    if tags:
        base_tags = list(dict.fromkeys(base_tags + list(tags)))
    if source_kind:
        base_tags.append(f"source:{source_kind}")
    if source_ref:
        base_tags.append(f"ref:{Path(source_ref).name[:80]}")

    own_store = store is None
    if own_store:
        store = open_store(project_id)

    written = 0
    skipped_empty = 0
    bumped = 0
    node_ids: List[str] = []
    ingested_fact_texts: List[str] = []

    seen: set = set()
    for raw in facts:
        if written >= max_facts:
            break
        fact = _cap_fact(raw, max_fact_chars)
        if len(fact) < 12:
            skipped_empty += 1
            continue
        norm = normalize_fact_text(fact)
        if norm in seen:
            continue
        seen.add(norm)

        node_id = semantic_content_id(project_id, fact)
        existing = store.get_node(node_id)
        if existing and isinstance(existing.data, dict):
            data = dict(existing.data)
            data["recurrence_count"] = int(data.get("recurrence_count", 1)) + 1
            data["reference_count"] = int(data.get("reference_count", 0)) + 1
            if source_ref:
                refs = list(data.get("source_refs") or [])
                if source_ref not in refs:
                    refs.append(source_ref)
                    data["source_refs"] = refs[-10:]
            store.update_node_data(node_id, data)
            bumped += 1
            node_ids.append(node_id)
            continue

        node = create_semantic_node(
            project_id=project_id,
            fact=fact,
            confidence=confidence,
            source_turn_id=source_turn_id,
            topic_cluster=cluster,
            tags=base_tags,
        )
        node.id = node_id
        node.metadata = {
            "source_kind": source_kind,
            "source_ref": source_ref,
        }
        store.write_node(node)
        node_ids.append(node_id)
        ingested_fact_texts.append(fact)
        written += 1

        if episode_node_id:
            try:
                edge = create_edge(
                    from_node=node_id,
                    to_node=episode_node_id,
                    edge_type=EdgeType.DERIVES_FROM,
                    project_id=project_id,
                    metadata={"source_kind": source_kind},
                )
                store.write_edge(edge)
            except Exception as edge_err:
                logger.debug("DERIVES_FROM edge skipped: %s", edge_err)

    result = {
        "written": written,
        "bumped": bumped,
        "skipped_empty": skipped_empty,
        "node_ids": node_ids,
        "topic_cluster": cluster,
    }

    # Mirror into ainl_native.db when native backend is configured (strict-native path)
    if ingested_fact_texts:
        try:
            import json as _json

            import ainl_native as _native

            sys_path_hooks = str(Path(__file__).resolve().parent.parent / "hooks")
            import sys

            if sys_path_hooks not in sys.path:
                sys.path.insert(0, sys_path_hooks)
            from shared.config import get_backend, is_strict_native

            if is_strict_native(True) or get_backend() == "native":
                native_db = (
                    Path.home()
                    / ".claude"
                    / "projects"
                    / project_id
                    / "graph_memory"
                    / "ainl_native.db"
                )
                _native.ingest_facts(
                    str(native_db),
                    project_id,
                    _json.dumps(
                        {
                            "facts": ingested_fact_texts,
                            "tags": base_tags,
                            "topic_cluster": cluster,
                            "confidence": confidence,
                            "source_kind": source_kind,
                        }
                    ),
                )
        except Exception:
            pass

    return result


def find_recent_episode_node_id(store, project_id: str, turn_id: Optional[str] = None) -> Optional[str]:
    """Resolve episode node for DERIVES_FROM linking."""
    if turn_id:
        try:
            episodes = store.query_by_type(NodeType.EPISODE, project_id, limit=30)
            for ep in episodes:
                d = ep.data if isinstance(ep.data, dict) else {}
                if d.get("turn_id") == turn_id:
                    return ep.id
        except Exception:
            pass
    try:
        recent = store.query_episodes_since(int(time.time()) - 600, limit=5, project_id=project_id)
        if recent:
            return recent[-1].id
    except Exception:
        pass
    return None


def record_knowledge_metrics(plugin_root: Path, event: str, payload: Dict[str, Any]) -> None:
    try:
        from pathlib import Path as _P

        sys_path_insert = str(plugin_root / "hooks")
        import sys

        if sys_path_insert not in sys.path:
            sys.path.insert(0, sys_path_insert)
        from shared.hook_metrics import append_hook_metric

        append_hook_metric(plugin_root, event, payload)
    except Exception:
        pass
