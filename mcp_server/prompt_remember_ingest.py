"""
Auto-ingest when the user asks to remember/save/commit content to graph memory.

Runs on UserPromptSubmit (after per-prompt capture flush) using:
- Pasted text in the current prompt (after stripping remember imperatives)
- Latest assistant reply from Claude Code transcript_path
- Recent tool digests / blobs from the session inbox
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .fact_extraction import extract_facts
    from .knowledge_config import default_topic_cluster, prompt_remember_cfg
    from .knowledge_writer import find_recent_episode_node_id, ingest_facts, open_store
    from .research_capture import run as run_research_capture
    from .transcript_tail import (
        read_recent_assistant_chunks,
        strip_remember_command_prefix,
    )
except ImportError:
    from fact_extraction import extract_facts
    from knowledge_config import default_topic_cluster, prompt_remember_cfg
    from knowledge_writer import find_recent_episode_node_id, ingest_facts, open_store
    from research_capture import run as run_research_capture
    from transcript_tail import (
        read_recent_assistant_chunks,
        strip_remember_command_prefix,
    )

logger = logging.getLogger(__name__)


def _load_recent_captures(plugin_root: Path, project_id: str, limit: int = 24) -> List[dict]:
    inbox = plugin_root / "inbox" / f"{project_id}_captures.jsonl"
    if not inbox.is_file():
        return []
    try:
        lines = inbox.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []
    out: List[dict] = []
    for line in lines[-limit:]:
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _captures_to_session_data(captures: List[dict]) -> dict:
    return {
        "tool_captures": captures,
        "files_touched": [],
        "tools_used": [],
        "had_errors": False,
    }


def _build_source_text(
    prompt: str,
    *,
    transcript_path: Optional[str],
    captures: List[dict],
    cfg: dict,
) -> tuple[str, List[str]]:
    """Return combined text and source labels for logging."""
    parts: List[str] = []
    labels: List[str] = []

    body = strip_remember_command_prefix(prompt)
    min_user = int(cfg.get("min_user_body_chars", 120))
    if len(body) >= min_user:
        cap = int(cfg.get("max_user_body_chars", 8000))
        parts.append(body[:cap])
        labels.append("user_prompt")

    if transcript_path:
        try:
            from .claude_paths import normalize_transcript_path
        except ImportError:
            from claude_paths import normalize_transcript_path
        tpath = str(normalize_transcript_path(transcript_path))
        ast = read_recent_assistant_chunks(
            tpath,
            max_messages=int(cfg.get("max_assistant_messages", 2)),
            max_chars=int(cfg.get("max_assistant_chars", 12000)),
            min_chars=int(cfg.get("min_assistant_chars", 80)),
        )
        if ast:
            parts.append(ast)
            labels.append("assistant_transcript")

    digest_lines: List[str] = []
    for cap in captures:
        digest = cap.get("tool_digest")
        if not digest:
            continue
        tool = cap.get("tool") or "tool"
        digest_lines.append(f"[{tool}] {digest[:600]}")
    if digest_lines:
        parts.append("\n".join(digest_lines[-12:]))
        labels.append("tool_digests")

    combined = "\n\n".join(parts).strip()
    max_total = int(cfg.get("max_combined_chars", 28000))
    if len(combined) > max_total:
        combined = combined[-max_total:]
    return combined, labels


def run(
    project_id: str,
    prompt: str,
    *,
    transcript_path: Optional[str] = None,
    plugin_root: Optional[Path] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extract facts from recent conversation context and write semantic nodes.
    """
    cfg = prompt_remember_cfg()
    if not cfg.get("enabled", True):
        return {"skipped": True, "reason": "disabled"}

    root = plugin_root or Path(__file__).resolve().parent.parent
    captures = _load_recent_captures(root, project_id)
    combined, labels = _build_source_text(
        prompt,
        transcript_path=transcript_path,
        captures=captures,
        cfg=cfg,
    )

    out: Dict[str, Any] = {
        "sources": labels,
        "combined_chars": len(combined),
        "written": 0,
        "skipped_duplicate_bump": 0,
    }

    if len(combined) < int(cfg.get("min_combined_chars", 100)):
        out["skipped"] = True
        out["reason"] = "insufficient_text"
        return out

    deadline = time.time() + float(cfg.get("time_budget_s", 2.0))
    store = open_store(project_id)
    ep_id = find_recent_episode_node_id(store, project_id, session_id)

    facts = extract_facts(
        combined,
        context="remember_request",
        max_facts=int(cfg.get("max_facts", 25)),
        max_fact_chars=int(cfg.get("max_fact_chars", 400)),
        use_llm=bool(cfg.get("use_llm_extraction", False)),
    )

    if facts and time.time() < deadline:
        tags = ["knowledge", "remember"]
        if session_id:
            tags.append(f"session:{session_id[:8]}")
        ing = ingest_facts(
            project_id,
            facts,
            source_kind="prompt_remember",
            source_ref=",".join(labels) or "prompt",
            tags=tags,
            topic_cluster=default_topic_cluster(project_id),
            source_turn_id=session_id,
            episode_node_id=ep_id,
            store=store,
            confidence=float(cfg.get("confidence", 0.88)),
        )
        out["written"] = int(ing.get("written", 0))
        out["skipped_duplicate_bump"] = int(ing.get("skipped_duplicate_bump", 0))

    if captures and time.time() < deadline and cfg.get("include_research_capture", True):
        try:
            rc = run_research_capture(
                project_id,
                _captures_to_session_data(captures),
                episode_data={"episode_node_id": ep_id, "turn_id": session_id},
                plugin_root=root,
                deadline_ts=deadline,
            )
            out["research_capture"] = rc
            out["written"] += int(rc.get("written", 0) or 0)
        except Exception as e:
            logger.debug("remember research_capture failed (non-fatal): %s", e)

    try:
        from shared.hook_metrics import append_hook_metric

        append_hook_metric(
            root,
            "prompt_remember_ingest",
            {
                "project_id": project_id,
                "written": out["written"],
                "sources": labels,
                "combined_chars": len(combined),
            },
        )
    except Exception:
        pass

    logger.info(
        "prompt_remember_ingest project=%s written=%s sources=%s",
        project_id,
        out["written"],
        labels,
    )
    return out
