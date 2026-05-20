"""Append-only JSONL metrics for hooks (recall, compression, cost ledger)."""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional


def metrics_path(plugin_root: Path) -> Path:
    p = plugin_root / "logs" / "hook_metrics.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def append_hook_metric(plugin_root: Path, event: str, payload: Dict[str, Any]) -> None:
    rec: Dict[str, Any] = {"ts": time.time(), "event": event}
    rec.update(payload)
    path = metrics_path(plugin_root)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def log_compression_applied(
    plugin_root: Path,
    *,
    project_id: str,
    surface: str,
    mode: str,
    mode_source: str,
    tokens_saved: int,
    savings_pct: float,
    original_tokens: int = 0,
    compressed_tokens: int = 0,
    preservation_score: Optional[float] = None,
    cache_preserved: Optional[bool] = None,
) -> None:
    """Record compression outcome for cost ledger (no prompt text)."""
    append_hook_metric(
        plugin_root,
        "compression_applied",
        {
            "project_id": project_id,
            "surface": surface,
            "mode": mode,
            "mode_source": mode_source,
            "tokens_saved": int(tokens_saved),
            "savings_pct": round(float(savings_pct), 2),
            "original_tokens": int(original_tokens),
            "compressed_tokens": int(compressed_tokens),
            "preservation_score": preservation_score,
            "cache_preserved": cache_preserved,
        },
    )


def _read_tail_records(plugin_root: Path, tail_lines: int = 4000) -> List[Dict[str, Any]]:
    path = metrics_path(plugin_root)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for line in lines[-tail_lines:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def read_last_recall_summary(plugin_root: Path, tail_lines: int = 400) -> Optional[Dict[str, Any]]:
    """Last recall_cycle row, if any."""
    for obj in reversed(_read_tail_records(plugin_root, tail_lines)):
        if obj.get("event") == "recall_cycle":
            return obj
    return None


def read_recent_events(
    plugin_root: Path,
    event: str,
    limit: int = 50,
    tail_lines: int = 2000,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for obj in reversed(_read_tail_records(plugin_root, tail_lines)):
        if obj.get("event") == event:
            out.append(obj)
            if len(out) >= limit:
                break
    out.reverse()
    return out


def aggregate_session_metrics(
    plugin_root: Path,
    since_ts: Optional[float] = None,
    tail_lines: int = 4000,
) -> Dict[str, Any]:
    """Aggregate cost-related metrics since ``since_ts`` (default: last 24h)."""
    if since_ts is None:
        since_ts = time.time() - 86400.0

    injected_chars = 0
    compression_saved_tokens = 0
    recall_skips: Counter = Counter()
    failure_warnings = 0
    tool_digests = 0
    compression_by_surface: Counter = Counter()
    turns_with_recall = 0

    for obj in _read_tail_records(plugin_root, tail_lines):
        if float(obj.get("ts", 0)) < since_ts:
            continue
        ev = obj.get("event")
        if ev == "recall_cycle":
            if not obj.get("skip_reason"):
                turns_with_recall += 1
                injected_chars += int(obj.get("recall_injected_chars", 0) or 0)
            else:
                recall_skips[str(obj.get("skip_reason"))] += 1
        elif ev == "recall_skip":
            recall_skips[str(obj.get("reason", "unknown"))] += 1
        elif ev == "compression_applied":
            compression_saved_tokens += int(obj.get("tokens_saved", 0) or 0)
            compression_by_surface[str(obj.get("surface", "?"))] += 1
        elif ev == "failure_warnings_injected":
            failure_warnings += int(obj.get("count", 0) or 0)
        elif ev == "tool_digest_created":
            tool_digests += 1

    return {
        "since_ts": since_ts,
        "injected_chars_est": injected_chars,
        "compression_saved_tokens_est": compression_saved_tokens,
        "recall_skips": dict(recall_skips),
        "failure_warnings_count": failure_warnings,
        "tool_digests_count": tool_digests,
        "compression_events_by_surface": dict(compression_by_surface),
        "turns_with_recall": turns_with_recall,
    }


def aggregate_project_metrics(
    plugin_root: Path,
    project_id: str,
    days: float = 7.0,
    tail_lines: int = 8000,
) -> Dict[str, Any]:
    since_ts = time.time() - days * 86400.0
    base = aggregate_session_metrics(plugin_root, since_ts=since_ts, tail_lines=tail_lines)
    base["project_id"] = project_id
    base["days"] = days

    project_injected = 0
    project_saved = 0
    for obj in _read_tail_records(plugin_root, tail_lines):
        if float(obj.get("ts", 0)) < since_ts:
            continue
        if obj.get("project_id") != project_id:
            continue
        if obj.get("event") == "recall_cycle" and not obj.get("skip_reason"):
            project_injected += int(obj.get("recall_injected_chars", 0) or 0)
        if obj.get("event") == "compression_applied":
            project_saved += int(obj.get("tokens_saved", 0) or 0)

    base["project_injected_chars_est"] = project_injected
    base["project_compression_saved_tokens_est"] = project_saved
    return base


def format_cost_banner_line(plugin_root: Path, since_ts: Optional[float] = None) -> str:
    """One-line cost summary for SessionStart banner."""
    agg = aggregate_session_metrics(plugin_root, since_ts=since_ts)
    parts: List[str] = []
    saved = agg.get("compression_saved_tokens_est", 0)
    if saved > 0:
        parts.append(f"eco ↓~{saved} tok")
    inj = agg.get("injected_chars_est", 0)
    if inj > 0:
        parts.append(f"MEM ~{inj // 4} tok inj")
    skips = agg.get("recall_skips") or {}
    skip_n = sum(int(v) for v in skips.values())
    if skip_n > 0:
        conv = int(skips.get("conversation_only", 0))
        if conv > 0:
            parts.append(f"recall skipped ×{conv} (chat)")
        elif skip_n > 0:
            parts.append(f"recall skipped ×{skip_n}")
    if not parts:
        return ""
    return "Cost: " + " · ".join(parts)
