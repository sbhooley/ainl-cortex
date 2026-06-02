"""
Topical FTS recall of content-knowledge semantic facts for prompt injection.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

try:
    from .knowledge_config import recall_cfg
    from .knowledge_writer import open_store
    from .node_types import NodeType
except ImportError:
    from knowledge_config import recall_cfg
    from knowledge_writer import open_store
    from node_types import NodeType

logger = logging.getLogger(__name__)


def _is_content_semantic(node) -> bool:
    if node.node_type != NodeType.SEMANTIC:
        return False
    data = node.data if isinstance(node.data, dict) else {}
    cluster = str(data.get("topic_cluster") or "")
    if cluster.startswith("_plugin:"):
        return False
    tags = data.get("tags") or []
    if cluster.startswith("knowledge:") or "knowledge" in tags:
        return True
    if any(str(t).startswith("source:") for t in tags):
        return True
    return bool(data.get("fact"))


def _query_terms(prompt: str, max_terms: int = 12) -> str:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", prompt.lower())
    stop = {
        "the", "and", "for", "what", "about", "your", "you", "did", "our",
        "that", "this", "with", "from", "have", "are", "was", "were",
    }
    kept = [w for w in words if w not in stop][:max_terms]
    return " OR ".join(kept) if kept else prompt[:120]


def format_topical_knowledge_block(project_id: str, prompt: str) -> Optional[str]:
    """Return markdown section of top semantic facts for this prompt, or None."""
    cfg = recall_cfg()
    if not cfg.get("topical_intent", True):
        return None
    limit = int(cfg.get("topical_fts_limit", 8))
    if not prompt.strip():
        return None

    keywords = [
        w.lower()
        for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", prompt)
        if w.lower()
        not in {
            "the", "and", "for", "what", "about", "your", "you", "did", "our",
            "that", "this", "with", "from", "have", "are", "was", "were", "say",
        }
    ][:12]

    try:
        store = open_store(project_id)
        nodes = store.search_fts(_query_terms(prompt), project_id, limit=limit * 3)
        if not nodes and keywords:
            for kw in keywords[:4]:
                nodes.extend(store.search_fts(kw, project_id, limit=limit))
        if not nodes:
            try:
                nodes = store.query_by_type(NodeType.SEMANTIC, project_id, limit=limit * 4)
            except Exception:
                nodes = []
    except Exception as e:
        logger.debug("topical FTS failed: %s", e)
        return None

    facts: List[str] = []
    seen: set = set()
    for node in nodes:
        if not _is_content_semantic(node):
            continue
        data = node.data if isinstance(node.data, dict) else {}
        fact = str(data.get("fact") or "").strip()
        if len(fact) < 15:
            continue
        if keywords:
            low = fact.lower()
            if not any(kw in low for kw in keywords):
                continue
        key = fact[:60].lower()
        if key in seen:
            continue
        seen.add(key)
        conf = getattr(node, "confidence", 0.7)
        facts.append(f"- {fact} (conf: {conf:.2f})")
        if len(facts) >= limit:
            break

    if not facts:
        return None
    return "## Relevant knowledge (from prior research & artifacts)\n" + "\n".join(facts)
