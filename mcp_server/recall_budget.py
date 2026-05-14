"""
Recall budget + markdown packing for Python and native recall paths.

Used by hooks (``user_prompt_submit``) and may be reused by MCP helpers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class RecallBudget:
    """Caps for recall assembly (chars + per-section item counts)."""

    max_chars: int
    native_max_chars: int
    max_episodes: int
    max_facts: int
    max_patterns: int
    max_failures: int
    max_persona: int
    detail_level: str  # minimal | standard | verbose
    min_prompt_chars_for_recall: int

    def effective_native_max(self) -> int:
        return self.native_max_chars if self.native_max_chars > 0 else self.max_chars


def recall_budget_from_memory_config(mem: Dict[str, Any]) -> RecallBudget:
    """Build ``RecallBudget`` from the ``memory`` block of plugin config."""
    mem = mem if isinstance(mem, dict) else {}
    max_tok = int(mem.get("max_context_tokens", 800) or 800)
    default_chars = max_tok * 4
    max_chars = mem.get("recall_max_chars")
    if max_chars is None:
        max_chars = default_chars
    max_chars = int(max_chars)

    native_raw = mem.get("recall_native_max_chars")
    native_max = int(native_raw) if native_raw is not None else max_chars

    items = mem.get("recall_max_items_per_type") or {}
    if not isinstance(items, dict):
        items = {}

    detail = str(mem.get("recall_detail_level", "standard") or "standard").lower()
    if detail not in ("minimal", "standard", "verbose"):
        detail = "standard"

    min_prompt = int(mem.get("recall_min_prompt_chars", 60) or 60)

    verb = detail == "verbose"
    return RecallBudget(
        max_chars=max_chars,
        native_max_chars=native_max,
        max_episodes=int(items.get("episodes", 5 if verb else 3)),
        max_facts=int(items.get("facts", 8 if verb else 5)),
        max_patterns=int(items.get("patterns", 4 if verb else 2)),
        max_failures=int(items.get("failures", 5 if verb else 3)),
        max_persona=int(items.get("persona", 5 if verb else 3)),
        detail_level=detail,
        min_prompt_chars_for_recall=min_prompt,
    )


def apply_char_ceiling(text: str, max_chars: int) -> Tuple[str, bool]:
    """Hard-cap ``text`` to ``max_chars`` with a single-line truncation marker."""
    if max_chars <= 0:
        return "", True
    marker = "\n\n[... truncated for recall budget]"
    if len(text) <= max_chars:
        return text, False
    take = max(0, max_chars - len(marker))
    return text[:take] + marker, True


def _norm_episode(ep: Any) -> Dict[str, Any]:
    if hasattr(ep, "data"):
        d = ep.data or {}
        created = getattr(ep, "created_at", 0)
        nid = str(getattr(ep, "id", ""))
    else:
        d = (ep or {}).get("data") or {}
        created = (ep or {}).get("created_at", 0)
        nid = str((ep or {}).get("id", ""))
    return {"id": nid, "created_at": created, "data": d}


def format_memory_context_markdown(
    context: Dict[str, Any],
    budget: RecallBudget,
    apply_char_cap: bool = True,
) -> Tuple[str, Dict[str, Any]]:
    """
    Turn a ``compile_memory_context`` dict into tiered markdown.

    Returns ``(markdown, stats)`` where stats includes counts and truncation flags.
    """
    detail = budget.detail_level
    lines_summary: List[str] = []
    lines_detail: List[str] = []

    episodes = [_norm_episode(e) for e in (context.get("recent_episodes") or [])]
    facts = list(context.get("relevant_facts") or [])
    patterns = list(context.get("applicable_patterns") or [])
    failures = list(context.get("known_failures") or [])
    traits = list(context.get("persona_traits") or [])

    ep_limit = 1 if detail == "minimal" else budget.max_episodes
    fact_limit = budget.max_facts
    pat_limit = 1 if detail == "minimal" else budget.max_patterns
    fail_limit = budget.max_failures
    persona_limit = 0 if detail == "minimal" else budget.max_persona

    if facts:
        lines_summary.append("**Known facts:**")
        for fact in facts[:fact_limit]:
            fd = fact["data"] if isinstance(fact, dict) else getattr(fact, "data", {}) or {}
            fact_text = str(fd.get("fact", ""))[:120]
            conf = float(fact.get("confidence", getattr(fact, "confidence", 0.5)))
            lines_summary.append(f"- {fact_text} (conf: {conf:.2f})")
        lines_summary.append("")

    if failures:
        lines_summary.append("**Known issues:**")
        for fail in failures[:fail_limit]:
            fd = fail["data"] if isinstance(fail, dict) else getattr(fail, "data", {}) or {}
            file = fd.get("file", "unknown")
            line_num = fd.get("line", "?")
            msg = str(fd.get("error_message", ""))[:80]
            lines_summary.append(f"- {file}:{line_num}: {msg}")
        lines_summary.append("")

    if patterns and detail != "minimal":
        lines_summary.append("**Reusable patterns:**")
        for pat in patterns[:pat_limit]:
            pd = pat["data"] if isinstance(pat, dict) else getattr(pat, "data", {}) or {}
            name = pd.get("pattern_name", "")
            seq = pd.get("tool_sequence") or []
            seq_s = " → ".join(seq[:4])
            fitness = float(pd.get("fitness", 0.0))
            lines_summary.append(f"- \"{name}\": {seq_s} (fitness: {fitness:.2f})")
        lines_summary.append("")

    if detail == "minimal" and episodes:
        ep = episodes[0]
        ts = time.strftime("%Y-%m-%d", time.localtime(ep["created_at"]))
        task = str(ep["data"].get("task_description", ""))[:80]
        outcome = ep["data"].get("outcome", "")
        lines_summary.append(f"**Latest work:** [{ts}] {task} → {outcome}")
        lines_summary.append("")

    if detail != "minimal" and episodes:
        lines_detail.append("**Recent work:**")
        for ep in episodes[:ep_limit]:
            ts = time.strftime("%Y-%m-%d", time.localtime(ep["created_at"]))
            task = str(ep["data"].get("task_description", ""))[:80]
            outcome = ep["data"].get("outcome", "")
            lines_detail.append(f"- [{ts}] {task} → {outcome}")
        lines_detail.append("")

    if detail == "verbose" and traits:
        trait_strs = []
        for trait in traits[:persona_limit]:
            td = trait["data"] if isinstance(trait, dict) else getattr(trait, "data", {}) or {}
            name = td.get("trait_name", "")
            strength = float(td.get("strength", 0.0))
            trait_strs.append(f"{name} ({strength:.2f})")
        if trait_strs:
            lines_detail.append(f"**Project style:** {', '.join(trait_strs)}")
            lines_detail.append("")

    out_parts: List[str] = ["## Memory (summary)", ""]
    out_parts.extend(lines_summary)
    if lines_detail and detail in ("standard", "verbose"):
        out_parts.extend(["## Memory (details)", ""])
        out_parts.extend(lines_detail)

    text = "\n".join(out_parts).rstrip() + "\n"
    if apply_char_cap:
        capped, truncated = apply_char_ceiling(text, budget.max_chars)
    else:
        capped, truncated = text, False

    stats = {
        "recall_budget_chars": budget.max_chars,
        "recall_injected_chars": len(capped) if apply_char_cap else len(text),
        "recall_truncated": truncated if apply_char_cap else False,
        "recall_detail_level": detail,
        "sections": {
            "episodes_used": min(len(episodes), ep_limit),
            "facts_used": min(len(facts), fact_limit),
            "patterns_used": min(len(patterns), pat_limit),
            "failures_used": min(len(failures), fail_limit),
        },
    }
    return capped, stats


def pack_native_brief(
    prebuilt: str,
    budget: RecallBudget,
    compress: bool,
    project_id: str,
    compress_fn: Callable[[str, str], Tuple[str, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]],
) -> Tuple[str, Optional[Dict[str, Any]], Optional[Dict[str, Any]], Dict[str, Any]]:
    """Apply optional compression then char ceiling for native ``brief`` strings."""
    brief = prebuilt or ""
    compression_metrics = None
    pipeline_stats = None
    if compress and brief.strip():
        brief, compression_metrics, pipeline_stats = compress_fn(brief, project_id)
    max_c = budget.effective_native_max()
    brief, truncated = apply_char_ceiling(brief, max_c)
    stats = {
        "recall_budget_chars": max_c,
        "recall_injected_chars": len(brief),
        "recall_truncated": truncated,
        "path": "native",
    }
    return brief, compression_metrics, pipeline_stats, stats


def memory_brief_has_content(brief: str) -> bool:
    """True if the packed brief is more than empty headings / whitespace."""
    if not brief or not brief.strip():
        return False
    for line in brief.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("-") or s.startswith("**"):
            return True
    return False
