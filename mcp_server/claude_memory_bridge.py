"""
Optional mirror of Claude Code reference_*.md memory into graph semantics.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .fact_extraction import extract_facts_heuristic
    from .knowledge_config import bridge_cfg
    from .knowledge_writer import ingest_facts, open_store
except ImportError:
    from fact_extraction import extract_facts_heuristic
    from knowledge_config import bridge_cfg
    from knowledge_writer import ingest_facts, open_store

logger = logging.getLogger(__name__)

_BULLET_RE = re.compile(r"^[\s]*(?:[-*•]|\d+\.)\s+(.+)$", re.MULTILINE)


def _resolve_memory_dir(project_id: str, cwd: Optional[Path] = None) -> Optional[Path]:
    """Map project_id to ~/.claude/projects/<encoded>/memory when possible."""
    cfg = bridge_cfg()
    mem_name = cfg.get("memory_dir_name") or "memory"
    try:
        from .claude_paths import candidate_claude_memory_dirs
    except ImportError:
        from claude_paths import candidate_claude_memory_dirs

    for c in candidate_claude_memory_dirs(cwd, memory_dir_name=mem_name):
        if c.is_dir():
            return c
    return None


def run(
    project_id: str,
    *,
    cwd: Optional[Path] = None,
    plugin_root: Optional[Path] = None,
    force: bool = False,
) -> Dict[str, Any]:
    cfg = bridge_cfg()
    if not cfg.get("enabled", False) and not force:
        return {"skipped": True, "reason": "disabled"}

    mem_dir = _resolve_memory_dir(project_id, cwd)
    if not mem_dir:
        return {"skipped": True, "reason": "no_memory_dir"}

    prefix = cfg.get("file_prefix") or "reference_"
    max_per_file = int(cfg.get("max_facts_per_file", 30))
    store = open_store(project_id)
    total_written = 0

    for path in sorted(mem_dir.glob(f"{prefix}*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        bullets = [m.group(1).strip() for m in _BULLET_RE.finditer(text) if len(m.group(1)) >= 15]
        facts = bullets[:max_per_file]
        if not facts:
            facts = extract_facts_heuristic(
                text, max_facts=max_per_file, max_fact_chars=400, context_title=path.name
            )
        if not facts:
            continue
        result = ingest_facts(
            project_id,
            facts,
            source_kind="claude_memory",
            source_ref=str(path),
            tags=["from:claude-memory", f"file:{path.name}"],
            confidence=0.9,
            store=store,
        )
        total_written += result.get("written", 0) + result.get("bumped", 0)

    return {"memory_dir": str(mem_dir), "written": total_written}
