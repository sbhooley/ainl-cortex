"""Append-only JSONL metrics for hooks (recall, stop, session timing)."""

from __future__ import annotations

import json
import time
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


def read_last_recall_summary(plugin_root: Path, tail_lines: int = 400) -> Optional[Dict[str, Any]]:
    """Last ``recall_cycle`` or ``user_prompt_submit_recall`` row, if any."""
    path = metrics_path(plugin_root)
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines[-tail_lines:]):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("event") in ("recall_cycle", "user_prompt_submit_recall"):
            return obj
    return None


def read_recent_events(
    plugin_root: Path,
    event: str,
    limit: int = 50,
    tail_lines: int = 2000,
) -> List[Dict[str, Any]]:
    path = metrics_path(plugin_root)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for line in reversed(lines[-tail_lines:]):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("event") == event:
            out.append(obj)
            if len(out) >= limit:
                break
    out.reverse()
    return out
