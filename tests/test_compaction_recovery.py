"""
Tests for compaction recovery brief:
  - build_compaction_brief: returns empty string when no delta file
  - Parses last N sessions from delta log
  - Respects max_age_days cutoff
  - Formats correctly (session_id prefix, node counts, type summary)
  - Handles malformed lines gracefully
"""

import sys
import json
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

from shared.session_delta import build_compaction_brief, append_session_delta


def _write_delta(plugin_root, session_id, project_id, started_at, nodes, finalized_ago_s=10):
    """Write a delta record with a backdated finalized_at."""
    import json as _json, time as _time
    delta_dir = plugin_root / "logs"
    delta_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "session_id": session_id,
        "project_id": project_id,
        "started_at": round(started_at, 3),
        "finalized_at": round(_time.time() - finalized_ago_s, 3),
        "node_count": len(nodes),
        "nodes": nodes,
    }
    with open(delta_dir / "session_deltas.jsonl", "a", encoding="utf-8") as f:
        f.write(_json.dumps(record) + "\n")


# ── basic behaviour ───────────────────────────────────────────────────────────

def test_empty_when_no_file(tmp_path):
    assert build_compaction_brief(tmp_path) == ""


def test_empty_when_file_is_empty(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "session_deltas.jsonl").write_text("")
    assert build_compaction_brief(tmp_path) == ""


def test_returns_nonempty_with_recent_delta(tmp_path):
    _write_delta(tmp_path, "sid-aaa", "proj", time.time() - 100,
                 [{"node_id": "n1", "node_type": "episode", "content_hash": "abc"}],
                 finalized_ago_s=60)
    brief = build_compaction_brief(tmp_path)
    assert brief != ""
    assert "sid-aaa"[:8] in brief


def test_includes_node_count(tmp_path):
    nodes = [
        {"node_id": f"n{i}", "node_type": "semantic", "content_hash": "x"}
        for i in range(4)
    ]
    _write_delta(tmp_path, "sid-bbb", "proj", time.time() - 100, nodes, finalized_ago_s=60)
    brief = build_compaction_brief(tmp_path)
    assert "4" in brief


def test_includes_node_type_summary(tmp_path):
    nodes = [
        {"node_id": "n1", "node_type": "episode", "content_hash": "x"},
        {"node_id": "n2", "node_type": "failure", "content_hash": "y"},
        {"node_id": "n3", "node_type": "failure", "content_hash": "z"},
    ]
    _write_delta(tmp_path, "sid-ccc", "proj", time.time() - 100, nodes, finalized_ago_s=60)
    brief = build_compaction_brief(tmp_path)
    assert "episode" in brief
    assert "failure" in brief


# ── max_sessions cap ──────────────────────────────────────────────────────────

def test_respects_max_sessions(tmp_path):
    for i in range(5):
        _write_delta(tmp_path, f"sid-{i:04d}", "proj", time.time() - 100,
                     [{"node_id": "n", "node_type": "episode", "content_hash": "x"}],
                     finalized_ago_s=i * 10 + 5)
    brief = build_compaction_brief(tmp_path, max_sessions=3)
    # Each session appears as one bullet line
    lines = [l for l in brief.splitlines() if l.strip().startswith("-")]
    assert len(lines) == 3


# ── max_age_days cutoff ───────────────────────────────────────────────────────

def test_skips_stale_sessions(tmp_path):
    _write_delta(tmp_path, "sid-old", "proj", time.time() - 40 * 86400,
                 [{"node_id": "n", "node_type": "episode", "content_hash": "x"}],
                 finalized_ago_s=40 * 86400)
    brief = build_compaction_brief(tmp_path, max_age_days=30)
    assert brief == ""


def test_includes_recent_skips_old(tmp_path):
    _write_delta(tmp_path, "sid-old", "proj", time.time() - 40 * 86400,
                 [{"node_id": "n", "node_type": "episode", "content_hash": "x"}],
                 finalized_ago_s=40 * 86400)
    _write_delta(tmp_path, "sid-new", "proj", time.time() - 100,
                 [{"node_id": "n", "node_type": "episode", "content_hash": "x"}],
                 finalized_ago_s=60)
    brief = build_compaction_brief(tmp_path, max_age_days=30)
    assert "sid-new"[:8] in brief
    assert "sid-old"[:8] not in brief


# ── resilience ───────────────────────────────────────────────────────────────

def test_handles_malformed_lines(tmp_path):
    delta_dir = tmp_path / "logs"
    delta_dir.mkdir()
    f = delta_dir / "session_deltas.jsonl"
    f.write_text("not json\n{}\n")
    # Should not raise
    brief = build_compaction_brief(tmp_path)
    assert isinstance(brief, str)
