"""High-fitness procedural pattern cards for bounded recall injection."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def fetch_patterns_for_project(project_id: str, limit: int = 20) -> List[Any]:
    """Load procedural nodes from the Python graph store (native recall companion)."""
    try:
        from graph_store import get_graph_store
        from node_types import NodeType

        db = Path.home() / ".claude" / "projects" / project_id / "graph_memory" / "ainl_memory.db"
        if not db.exists():
            return []
        store = get_graph_store(db)
        return store.query_by_type(
            NodeType.PROCEDURAL,
            project_id,
            limit,
        ) or []
    except Exception:
        return []


def _pattern_text(pat: Any) -> str:
    if hasattr(pat, "data"):
        d = pat.data or {}
    else:
        d = (pat or {}).get("data") or {}
    name = str(d.get("pattern_name", ""))
    seq = d.get("tool_sequence") or []
    return f"{name} {' '.join(seq)}".strip()


def match_procedure_cards(
    prompt: str,
    patterns: List[Any],
    *,
    min_fitness: float = 0.5,
    max_cards: int = 2,
) -> List[Tuple[Any, float]]:
    """Return top procedural patterns by simple token overlap with prompt."""
    if not prompt or not patterns:
        return []
    prompt_tokens = set(re.findall(r"[a-z0-9_]+", prompt.lower()))
    if not prompt_tokens:
        return []

    scored: List[Tuple[Any, float]] = []
    for pat in patterns:
        d = pat.data if hasattr(pat, "data") else (pat or {}).get("data") or {}
        fitness = float(d.get("fitness", 0.0))
        if fitness < min_fitness:
            continue
        text = _pattern_text(pat).lower()
        ptoks = set(re.findall(r"[a-z0-9_]+", text))
        if not ptoks:
            continue
        overlap = len(prompt_tokens & ptoks) / max(1, len(prompt_tokens))
        if overlap < 0.15:
            continue
        scored.append((pat, overlap + fitness * 0.1))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:max_cards]


def format_procedure_cards_section(matches: List[Tuple[Any, float]]) -> str:
    if not matches:
        return ""
    lines = ["## Procedure cards", ""]
    for pat, score in matches:
        d = pat.data if hasattr(pat, "data") else (pat or {}).get("data") or {}
        name = d.get("pattern_name", "workflow")
        seq = d.get("tool_sequence") or []
        fitness = float(d.get("fitness", 0.0))
        steps = " → ".join(seq[:6]) if seq else "(no sequence)"
        lines.append(f"- **{name}** (fitness {fitness:.2f}): {steps}")
    lines.append("")
    return "\n".join(lines)
