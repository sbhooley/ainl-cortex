"""MCP-facing cost ledger aggregates (read-only, no prompt text)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional


def build_cost_snapshot(
    plugin_root: Path,
    project_id: Optional[str] = None,
    session_hours: float = 24.0,
    project_days: float = 7.0,
) -> Dict[str, Any]:
    import sys

    hooks = str(plugin_root / "hooks")
    if hooks not in sys.path:
        sys.path.insert(0, hooks)
    from shared.hook_metrics import aggregate_project_metrics, aggregate_session_metrics

    since_ts = time.time() - session_hours * 3600.0
    session = aggregate_session_metrics(plugin_root, since_ts=since_ts)
    out: Dict[str, Any] = {
        "ok": True,
        "session_hours": session_hours,
        "session": session,
        "scope_note": (
            "Estimates cover injected graph-memory brief and plugin compression only; "
            "not full Claude transcript or subscription billing."
        ),
    }
    if project_id:
        out["project"] = aggregate_project_metrics(
            plugin_root, project_id, days=project_days
        )
    return out
