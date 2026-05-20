"""hook_metrics.jsonl aggregation."""

import json
import time
from pathlib import Path

from hooks.shared.hook_metrics import (
    aggregate_session_metrics,
    append_hook_metric,
    format_cost_banner_line,
)


def test_aggregate_session_metrics(tmp_path):
    root = tmp_path / "plugin"
    (root / "logs").mkdir(parents=True)
    now = time.time()
    append_hook_metric(
        root,
        "compression_applied",
        {"tokens_saved": 100, "surface": "memory", "project_id": "p1"},
    )
    append_hook_metric(
        root,
        "recall_cycle",
        {"recall_injected_chars": 400, "project_id": "p1"},
    )
    append_hook_metric(
        root,
        "recall_skip",
        {"reason": "conversation_only", "project_id": "p1"},
    )
    agg = aggregate_session_metrics(root, since_ts=now - 60)
    assert agg["compression_saved_tokens_est"] >= 100
    assert agg["injected_chars_est"] >= 400
    assert agg["recall_skips"].get("conversation_only", 0) >= 1
    line = format_cost_banner_line(root, since_ts=now - 60)
    assert "Cost:" in line
