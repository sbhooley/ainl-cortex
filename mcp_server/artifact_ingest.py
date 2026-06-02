"""
Ingest markdown/plan artifacts from disk at session end.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    from .fact_extraction import extract_facts_from_markdown_file
    from .knowledge_config import artifact_cfg, get_knowledge_capture_block
    from .knowledge_writer import find_recent_episode_node_id, ingest_facts, open_store
except ImportError:
    from fact_extraction import extract_facts_from_markdown_file
    from knowledge_config import artifact_cfg, get_knowledge_capture_block
    from knowledge_writer import find_recent_episode_node_id, ingest_facts, open_store

logger = logging.getLogger(__name__)


def read_artifact_text(path: Path, max_bytes: int) -> Optional[str]:
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > max_bytes:
            logger.debug("Skip ingest (too large): %s", path)
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
        return text if len(text.strip()) >= artifact_cfg().get("min_chars", 200) else None
    except OSError as e:
        logger.debug("read_artifact_text failed %s: %s", path, e)
        return None


def _artifact_path_key(p: Path) -> str:
    """Stable dedupe key without failing on missing paths (Windows-safe)."""
    try:
        if p.is_file():
            return str(p.resolve())
    except OSError:
        pass
    return str(p.expanduser())


def collect_ingest_paths(session_data: dict) -> List[Path]:
    paths: List[Path] = []
    seen: set = set()
    for cap in session_data.get("tool_captures") or []:
        if not cap.get("ingest_candidate"):
            continue
        raw = cap.get("file")
        if not raw:
            continue
        p = Path(str(raw)).expanduser()
        key = _artifact_path_key(p)
        if key in seen:
            continue
        seen.add(key)
        paths.append(p)
    return paths


def run(
    project_id: str,
    session_data: dict,
    *,
    episode_data: Optional[dict] = None,
    plugin_root: Optional[Path] = None,
    deadline_ts: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Read ingest candidates from disk, extract facts, write semantic nodes.
    """
    cfg = artifact_cfg()
    if not cfg.get("enabled", True):
        return {"skipped": True, "reason": "disabled"}

    budget_ms = int(get_knowledge_capture_block().get("stop_time_budget_ms", 2500))
    deadline = deadline_ts or (time.time() + budget_ms / 1000.0)

    paths = collect_ingest_paths(session_data)
    if not paths:
        return {"paths": 0, "written": 0}

    store = open_store(project_id)
    ep_id = None
    turn_id = None
    if episode_data:
        turn_id = episode_data.get("turn_id")
        ep_id = episode_data.get("episode_node_id") or find_recent_episode_node_id(
            store, project_id, turn_id
        )

    total_written = 0
    total_bumped = 0
    per_file: List[Dict[str, Any]] = []

    max_bytes = int(cfg.get("max_file_bytes", 512_000))

    for path in paths:
        if time.time() >= deadline:
            logger.info("artifact_ingest: time budget exhausted")
            break
        text = read_artifact_text(path, max_bytes)
        if not text:
            continue
        facts = extract_facts_from_markdown_file(text, path.name)
        if not facts:
            continue
        result = ingest_facts(
            project_id,
            facts,
            source_kind="artifact",
            source_ref=str(path),
            tags=["artifact", f"file:{path.name}"],
            source_turn_id=turn_id,
            episode_node_id=ep_id,
            store=store,
        )
        total_written += result.get("written", 0)
        total_bumped += result.get("bumped", 0)
        per_file.append({"path": str(path), **result})

    if plugin_root and (total_written or total_bumped):
        try:
            try:
                from .knowledge_writer import record_knowledge_metrics
            except ImportError:
                from knowledge_writer import record_knowledge_metrics

            record_knowledge_metrics(
                plugin_root,
                "facts_ingested",
                {
                    "project_id": project_id,
                    "written": total_written,
                    "bumped": total_bumped,
                    "files": len(per_file),
                },
            )
        except Exception:
            pass

    return {
        "paths": len(paths),
        "written": total_written,
        "bumped": total_bumped,
        "files": per_file,
    }
