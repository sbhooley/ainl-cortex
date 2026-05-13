"""
Python-side anchored summary.

A single stable compressed document that synthesises all graph memory for a
project. Written at session end (Stop hook), injected at SessionStart, and
used to skip per-turn FTS recall when the content is fresh.

This mirrors the function of ainl_native.upsert_anchored_summary /
session_context for the Python (SQLiteGraphStore) backend.  When the native
backend is active the Rust crate owns this; when on Python this module owns it.
"""

import logging
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

# Stable namespace so the node UUID is deterministic per project
_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
_TOPIC = "_plugin:anchored_summary"
_MAX_AGE_SECONDS = 7 * 24 * 3600  # 7 days — beyond this, treat as stale


def _node_id(project_id: str) -> str:
    return str(uuid.uuid5(_NS, f"anchored_summary:{project_id}"))


def update_anchored_summary(store, project_id: str) -> bool:
    """
    Build and persist an anchored summary from the current graph memory.
    Called at session end (Stop hook) for the Python backend.
    Returns True if the summary was written.
    """
    try:
        import time as _time
        try:
            from node_types import GraphNode, NodeType
        except ImportError:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent))
            from node_types import GraphNode, NodeType

        from node_types import NodeType as _NT
        episodes = store.query_episodes_since(since=0, limit=30, project_id=project_id)
        facts = store.query_by_type(_NT.SEMANTIC, project_id=project_id, limit=20)
        patterns = store.query_by_type(_NT.PROCEDURAL, project_id=project_id, limit=10)

        if not episodes and not facts and not patterns:
            return False

        lines = []
        if episodes:
            lines.append("**Recent Work:**")
            for ep in episodes[-10:]:
                d = ep.data if hasattr(ep, 'data') else ep
                task = str(d.get("task_description", ""))[:80]
                outcome = str(d.get("outcome", ""))
                if task:
                    lines.append(f"- {task} → {outcome}")
            lines.append("")

        if facts:
            lines.append("**Key Facts:**")
            for f in facts[:10]:
                d = f.data if hasattr(f, 'data') else f
                # Skip other anchored summary nodes and internal plugin nodes
                if str(d.get("topic_cluster", "")).startswith("_plugin:"):
                    continue
                text = str(d.get("fact", d.get("content", "")))[:100]
                if text:
                    lines.append(f"- {text}")
            lines.append("")

        if patterns:
            lines.append("**Reusable Patterns:**")
            for p in patterns[:5]:
                d = p.data if hasattr(p, 'data') else p
                name = str(d.get("name", ""))
                desc = str(d.get("description", ""))[:80]
                if name:
                    lines.append(f"- {name}: {desc}")
            lines.append("")

        raw = "\n".join(lines).strip()
        if not raw:
            return False

        # Compress before storing
        compressed = raw
        original_len = len(raw)
        try:
            from compression_pipeline import get_compression_pipeline
            result = get_compression_pipeline().compress_memory_context(raw, project_id)
            if result and result.compressed_text:
                compressed = result.compressed_text
        except Exception:
            pass

        now = int(_time.time())
        node_id = _node_id(project_id)
        node = GraphNode(
            id=node_id,
            node_type=NodeType.SEMANTIC,
            project_id=project_id,
            created_at=now,
            updated_at=now,
            confidence=1.0,
            data={
                "fact": compressed,
                "topic_cluster": _TOPIC,
                "anchored_at": now,
                "episode_count": len(episodes),
                "fact_count": len(facts),
                "pattern_count": len(patterns),
                "original_chars": original_len,
                "compressed_chars": len(compressed),
            },
        )
        store.write_node(node)
        logger.info(
            f"Anchored summary updated: {original_len} → {len(compressed)} chars "
            f"({len(episodes)} episodes, {len(facts)} facts, {len(patterns)} patterns)"
        )
        return True

    except Exception as e:
        logger.debug(f"Anchored summary update failed (non-fatal): {e}")
        return False


def get_anchored_summary(store, project_id: str) -> Optional[str]:
    """
    Retrieve the anchored summary text for injection at SessionStart.
    Returns compressed summary string, or None if missing/stale.
    """
    try:
        node = store.get_node(_node_id(project_id))
        if not node:
            return None
        data = node.data if hasattr(node, 'data') else {}
        age = time.time() - data.get("anchored_at", 0)
        if age > _MAX_AGE_SECONDS:
            logger.debug(f"Anchored summary stale ({age/3600:.0f}h old), skipping")
            return None
        text = data.get("fact", "")
        return text if text.strip() else None
    except Exception as e:
        logger.debug(f"Anchored summary read failed (non-fatal): {e}")
        return None


def summary_stats(store, project_id: str) -> Optional[dict]:
    """Return metadata about the stored summary (for telemetry/display)."""
    try:
        node = store.get_node(_node_id(project_id))
        if not node:
            return None
        d = node.data if hasattr(node, 'data') else {}
        return {
            "anchored_at": d.get("anchored_at"),
            "episode_count": d.get("episode_count", 0),
            "fact_count": d.get("fact_count", 0),
            "pattern_count": d.get("pattern_count", 0),
            "original_chars": d.get("original_chars", 0),
            "compressed_chars": d.get("compressed_chars", 0),
        }
    except Exception:
        return None
