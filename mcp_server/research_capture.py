"""
Promote web_search / web_fetch digests and blobs into semantic facts.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .fact_extraction import extract_facts_heuristic
    from .knowledge_config import research_cfg
    from .knowledge_writer import find_recent_episode_node_id, ingest_facts, open_store
    from .tool_digest import load_tool_outcome_blob
except ImportError:
    from fact_extraction import extract_facts_heuristic
    from knowledge_config import research_cfg
    from knowledge_writer import find_recent_episode_node_id, ingest_facts, open_store
    from tool_digest import load_tool_outcome_blob

logger = logging.getLogger(__name__)

_WEB_TOOLS = frozenset({"web_search", "web_fetch"})


def _infer_topic_tags(text: str) -> List[str]:
    try:
        import ainl_native as native

        tags = native.infer_topics(text[:2000])
        if isinstance(tags, list):
            return [str(t) for t in tags[:8]]
    except Exception:
        pass
    # Heuristic topic tokens
    lower = text.lower()
    topics = []
    for term in (
        "linkedin",
        "tiktok",
        "youtube",
        "viral",
        "clipping",
        "algorithm",
        "caption",
        "research",
    ):
        if term in lower:
            topics.append(term)
    return topics[:8]


def run(
    project_id: str,
    session_data: dict,
    *,
    episode_data: Optional[dict] = None,
    plugin_root: Optional[Path] = None,
    deadline_ts: Optional[float] = None,
) -> Dict[str, Any]:
    cfg = research_cfg()
    if not cfg.get("enabled", True):
        return {"skipped": True}

    if deadline_ts and time.time() >= deadline_ts:
        return {"skipped": True, "reason": "deadline"}

    captures = session_data.get("tool_captures") or []
    web_caps = [c for c in captures if (c.get("tool") or "") in _WEB_TOOLS]
    if not web_caps:
        return {"web_captures": 0, "written": 0}

    store = open_store(project_id)
    turn_id = (episode_data or {}).get("turn_id")
    ep_id = (episode_data or {}).get("episode_node_id") or find_recent_episode_node_id(
        store, project_id, turn_id
    )

    max_facts = int(cfg.get("max_facts_per_session", 25))
    default_tags = list(cfg.get("default_tags") or ["research", "knowledge"])
    all_facts: List[str] = []

    for cap in web_caps:
        if len(all_facts) >= max_facts:
            break
        tool = cap.get("tool", "web")
        digest = cap.get("tool_digest") or ""
        blob_id = cap.get("tool_blob_id")
        blob_text = ""
        if blob_id:
            blob_text = load_tool_outcome_blob(project_id, blob_id) or ""
        source = blob_text or digest
        if not source or len(source.strip()) < 40:
            continue
        topics = _infer_topic_tags(source)
        tags = default_tags + [f"tool:{tool}"] + [f"topic:{t}" for t in topics]
        facts = extract_facts_heuristic(
            source,
            max_facts=min(12, max_facts - len(all_facts)),
            max_fact_chars=400,
            context_title=f"web:{tool}",
        )
        if not facts and digest:
            facts = [digest[:400]]
        for fact in facts:
            all_facts.append(fact)
            if len(all_facts) >= max_facts:
                break

    if not all_facts:
        return {"web_captures": len(web_caps), "written": 0}

    result = ingest_facts(
        project_id,
        all_facts,
        source_kind="research",
        source_ref="session:web_tools",
        tags=default_tags + ["research"],
        source_turn_id=turn_id,
        episode_node_id=ep_id,
        confidence=0.8,
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
                "research_facts",
                {"project_id": project_id, **result},
            )
        except Exception:
            pass

    return {"web_captures": len(web_caps), **result}
