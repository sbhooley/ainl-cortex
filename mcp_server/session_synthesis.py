"""
End-of-session durable fact synthesis when research/write tools were used.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from .fact_extraction import synthesize_session_facts
    from .knowledge_config import get_knowledge_capture_block, synthesis_cfg
    from .knowledge_writer import find_recent_episode_node_id, ingest_facts, open_store
    from .tool_digest import load_tool_outcome_blob
except ImportError:
    from fact_extraction import synthesize_session_facts
    from knowledge_config import get_knowledge_capture_block, synthesis_cfg
    from knowledge_writer import find_recent_episode_node_id, ingest_facts, open_store
    from tool_digest import load_tool_outcome_blob

logger = logging.getLogger(__name__)


def _session_triggers_met(session_data: dict) -> bool:
    syn = synthesis_cfg()
    triggers = set(syn.get("trigger_tools") or [])
    tools = set(session_data.get("tools_used") or [])
    for cap in session_data.get("tool_captures") or []:
        if cap.get("tool"):
            tools.add(cap["tool"])
    return bool(tools & triggers)


def run(
    project_id: str,
    session_data: dict,
    task_summary: str,
    *,
    episode_data: Optional[dict] = None,
    plugin_root: Optional[Path] = None,
    deadline_ts: Optional[float] = None,
) -> Dict[str, Any]:
    cfg = synthesis_cfg()
    if not cfg.get("enabled", True):
        return {"skipped": True}
    if deadline_ts and time.time() >= deadline_ts:
        return {"skipped": True, "reason": "deadline"}
    if not _session_triggers_met(session_data):
        return {"skipped": True, "reason": "no_trigger_tools"}

    extra_blob = []
    for cap in session_data.get("tool_captures") or []:
        bid = cap.get("tool_blob_id")
        if bid:
            t = load_tool_outcome_blob(project_id, bid)
            if t:
                extra_blob.append(t[:8000])

    facts = synthesize_session_facts(
        task_summary,
        session_data.get("tool_captures") or [],
        extra_blob_text="\n".join(extra_blob)[:16000],
    )
    min_facts = int(cfg.get("min_facts", 5))
    if len(facts) < min_facts:
        return {"skipped": True, "reason": "insufficient_facts", "candidates": len(facts)}

    store = open_store(project_id)
    turn_id = (episode_data or {}).get("turn_id")
    ep_id = (episode_data or {}).get("episode_node_id") or find_recent_episode_node_id(
        store, project_id, turn_id
    )

    result = ingest_facts(
        project_id,
        facts,
        source_kind="session_synthesis",
        source_ref="session:synthesis",
        tags=["synthesis", "session"],
        source_turn_id=turn_id,
        episode_node_id=ep_id,
        confidence=0.82,
        store=store,
    )

    if plugin_root:
        try:
            try:
                from .knowledge_writer import record_knowledge_metrics
            except ImportError:
                from knowledge_writer import record_knowledge_metrics

            record_knowledge_metrics(
                plugin_root,
                "synthesis_facts",
                {"project_id": project_id, **result},
            )
        except Exception:
            pass

    return result
