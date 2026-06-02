"""
Heuristic and optional LLM fact extraction from artifacts and session text.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

try:
    from .knowledge_config import extraction_llm_cfg, synthesis_cfg
except ImportError:
    from knowledge_config import extraction_llm_cfg, synthesis_cfg

logger = logging.getLogger(__name__)

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_HEADER_RE = re.compile(r"^#{1,4}\s+(.+)$", re.MULTILINE)
_BULLET_RE = re.compile(r"^[\s]*(?:[-*•]|\d+\.)\s+(.+)$", re.MULTILINE)
_NUMERIC_SENTENCE_RE = re.compile(
    r"[^.!?\n]*(?:\d+%|\d+\s*(?:kbps|Mbps|ms|min|sec|seconds|minutes|hours|days)|"
    r"\d{1,3}:\d{2})[^.!?\n]*[.!?]",
    re.IGNORECASE,
)


def _normalize_candidates(candidates: Sequence[str], max_facts: int, max_len: int) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for raw in candidates:
        line = " ".join((raw or "").split()).strip()
        if len(line) < 12:
            continue
        if len(line) > max_len:
            line = line[: max_len - 3].rstrip() + "..."
        key = line[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
        if len(out) >= max_facts:
            break
    return out


def extract_facts_heuristic(
    text: str,
    *,
    max_facts: int = 40,
    max_fact_chars: int = 400,
    context_title: str = "",
) -> List[str]:
    """Offline extraction: headers, bullets, bold, numeric sentences."""
    if not text or not text.strip():
        return []

    candidates: List[str] = []
    if context_title:
        candidates.append(f"Document '{context_title}' covers: {context_title[:120]}")

    for m in _HEADER_RE.finditer(text):
        title = m.group(1).strip()
        if len(title) >= 8:
            candidates.append(f"Section: {title}")

    for m in _BULLET_RE.finditer(text):
        bullet = m.group(1).strip()
        if len(bullet) >= 20:
            candidates.append(bullet)

    for m in _BOLD_RE.finditer(text):
        bold = m.group(1).strip()
        if len(bold) >= 15:
            candidates.append(bold)

    for m in _NUMERIC_SENTENCE_RE.finditer(text):
        sent = m.group(0).strip()
        if 25 <= len(sent) <= max_fact_chars:
            candidates.append(sent)

    # Paragraph fallbacks (first sentence of substantial paragraphs)
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split()).strip()
        if len(para) < 80 or len(para) > 600:
            continue
        first = re.split(r"(?<=[.!?])\s+", para)[0]
        if len(first) >= 40:
            candidates.append(first)

    return _normalize_candidates(candidates, max_facts, max_fact_chars)


def extract_facts_from_markdown_file(
    content: str,
    filename: str,
    *,
    max_facts: Optional[int] = None,
) -> List[str]:
    try:
        from .knowledge_config import artifact_cfg
    except ImportError:
        from knowledge_config import artifact_cfg

    cfg = artifact_cfg()
    max_facts = max_facts or int(cfg.get("max_facts_per_artifact", 40))
    max_len = int(cfg.get("max_fact_chars", 400))
    return extract_facts_heuristic(
        content,
        max_facts=max_facts,
        max_fact_chars=max_len,
        context_title=filename,
    )


def _llm_extract_facts(text: str, context: str, max_facts: int) -> Optional[List[str]]:
    try:
        import sys
        from pathlib import Path

        hooks = Path(__file__).resolve().parent.parent / "hooks"
        if str(hooks) not in sys.path:
            sys.path.insert(0, str(hooks))
        from shared.llm_client import complete_json_facts

        return complete_json_facts(text, context=context, max_facts=max_facts)
    except Exception as e:
        logger.debug("LLM extraction failed (fallback to heuristic): %s", e)
        return None


def extract_facts(
    text: str,
    *,
    context: str = "",
    max_facts: int = 40,
    max_fact_chars: int = 400,
    use_llm: Optional[bool] = None,
) -> List[str]:
    """Heuristic first; optional LLM when enabled and key present."""
    heuristic = extract_facts_heuristic(
        text, max_facts=max_facts, max_fact_chars=max_fact_chars, context_title=context
    )
    llm_cfg = extraction_llm_cfg()
    if use_llm is None:
        use_llm = bool(llm_cfg.get("enabled"))
    if not use_llm:
        return heuristic

    llm_max = int(llm_cfg.get("max_facts", max_facts))
    llm_facts = _llm_extract_facts(
        text[: int(llm_cfg.get("max_input_chars", 24000))],
        context=context,
        max_facts=llm_max,
    )
    if llm_facts:
        merged = list(llm_facts) + heuristic
        return _normalize_candidates(merged, max_facts, max_fact_chars)
    return heuristic


def synthesize_session_facts_heuristic(
    session_summary: str,
    tool_captures: Sequence[Dict[str, Any]],
    *,
    min_facts: int = 5,
    max_facts: int = 15,
) -> List[str]:
    """Build session-level facts from captures and summary without LLM."""
    candidates: List[str] = []
    tools = set()
    files: List[str] = []
    for cap in tool_captures:
        t = cap.get("tool") or ""
        if t:
            tools.add(t)
        f = cap.get("file")
        if f:
            files.append(str(f))
        digest = cap.get("tool_digest")
        if digest and isinstance(digest, str):
            for line in digest.splitlines():
                line = line.strip()
                if len(line) >= 25 and not line.startswith("tool="):
                    candidates.append(line[:400])

    if tools:
        candidates.append(
            f"Session used tools: {', '.join(sorted(tools)[:8])}"
        )
    if files:
        names = [__import__("pathlib").Path(f).name for f in files[:6]]
        candidates.append(f"Session touched artifacts: {', '.join(names)}")

    candidates.extend(
        extract_facts_heuristic(session_summary, max_facts=max_facts, max_fact_chars=400)
    )
    facts = _normalize_candidates(candidates, max_facts, 400)
    if len(facts) < min_facts and session_summary:
        facts.append(f"Session summary: {session_summary[:350]}")
    return facts[:max_facts]


def synthesize_session_facts(
    session_summary: str,
    tool_captures: Sequence[Dict[str, Any]],
    *,
    extra_blob_text: str = "",
) -> List[str]:
    """Session synthesis: heuristic + optional LLM."""
    syn = synthesis_cfg()
    min_facts = int(syn.get("min_facts", 5))
    max_facts = int(syn.get("max_facts", 15))

    blob_parts = [session_summary]
    for cap in tool_captures:
        if cap.get("tool_digest"):
            blob_parts.append(str(cap["tool_digest"]))
    if extra_blob_text:
        blob_parts.append(extra_blob_text)

    combined = "\n\n".join(p for p in blob_parts if p)
    llm_cfg = extraction_llm_cfg()
    if llm_cfg.get("enabled"):
        llm_facts = _llm_extract_facts(
            combined[: int(llm_cfg.get("max_input_chars", 24000))],
            context="session_synthesis",
            max_facts=max_facts,
        )
        if llm_facts and len(llm_facts) >= min_facts:
            return _normalize_candidates(llm_facts, max_facts, 400)

    return synthesize_session_facts_heuristic(
        session_summary,
        tool_captures,
        min_facts=min_facts,
        max_facts=max_facts,
    )
