"""cortex_cost_snapshot MCP helper."""

import time
from pathlib import Path

from hooks.shared.hook_metrics import append_hook_metric
from mcp_server.cortex_cost_snapshot import build_cost_snapshot

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def test_build_cost_snapshot():
    now = time.time()
    append_hook_metric(
        PLUGIN_ROOT,
        "compression_applied",
        {"tokens_saved": 50, "surface": "user_prompt", "project_id": "pytest_cost_snap"},
    )
    snap = build_cost_snapshot(
        PLUGIN_ROOT,
        project_id="pytest_cost_snap",
        session_hours=1.0,
        project_days=1.0,
    )
    assert snap["ok"] is True
    assert snap["session"]["compression_saved_tokens_est"] >= 50
    assert "scope_note" in snap
    assert snap["project"]["project_id"] == "pytest_cost_snap"
