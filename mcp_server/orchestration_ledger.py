"""Counterfactual orchestration savings vs chat repetition (baseline-tagged estimates)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

# Analytical orchestration tokens per chat-style repeat (baseline C order-of-magnitude).
# Source: AI_Native_Lang docs/CLAIMS_AND_EVIDENCE.md — not live billing.
EST_ORCH_TOKENS_PER_CHAT_REPEAT = 2500
BASELINE_TAG = "baseline_C_analytical"


def trajectory_fingerprint(tool_sequence: List[str]) -> str:
    sig = "|".join(tool_sequence[:20])
    return hashlib.sha256(sig.encode()).hexdigest()[:16]


def count_similar_trajectories(
    episodes_path: Path,
    fingerprint: str,
    min_count: int = 5,
) -> int:
    """Count episodes whose stored tool_sequence fingerprint matches."""
    if not episodes_path.exists():
        return 0
    # Placeholder: scan inbox capture buffer if present
    buf = episodes_path.parent.parent / "inbox" / "trajectory_fingerprints.jsonl"
    if not buf.exists():
        return 0
    n = 0
    try:
        for line in buf.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("fingerprint") == fingerprint:
                n += 1
    except Exception:
        return 0
    return n


def promotion_suggestion(
    recurrence_count: int,
    example_path: str = "examples/compact/hello_compact.ainl",
) -> Dict[str, Any]:
    if recurrence_count < 5:
        return {"suggest": False, "recurrence_count": recurrence_count}
    counterfactual_saved = recurrence_count * EST_ORCH_TOKENS_PER_CHAT_REPEAT
    return {
        "suggest": True,
        "recurrence_count": recurrence_count,
        "baseline_tag": BASELINE_TAG,
        "est_orchestration_tokens_per_chat_repeat": EST_ORCH_TOKENS_PER_CHAT_REPEAT,
        "est_tokens_saved_if_ainl": counterfactual_saved,
        "scope_note": (
            "Analytical orchestration-token estimate only; not subscription or API billing."
        ),
        "example_path": example_path,
        "recommended_tools": ["ainl_get_started", "ainl_validate", "ainl_compile", "ainl_run"],
    }


def format_promotion_nudge(suggestion: Dict[str, Any]) -> str:
    if not suggestion.get("suggest"):
        return ""
    return (
        f"AINL promotion ({suggestion['baseline_tag']}): similar workflow ran "
        f"{suggestion['recurrence_count']}× in chat — compiling once via "
        f"`ainl_run` may save ~{suggestion['est_tokens_saved_if_ainl']:,} orchestration tokens "
        f"(estimate). Start from {suggestion['example_path']}."
    )
