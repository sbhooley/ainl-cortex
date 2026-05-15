"""
Tests for failure trend clustering:
  - get_failure_trends: groups by (error_type, tool), respects since_days + min_count
  - format_warnings includes trend block when trends present
  - format_warnings works with warnings=[] but trends non-empty
  - Trends isolated by project
"""

import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))

from graph_store import get_graph_store
from node_types import GraphNode, NodeType, create_failure_node, failure_content_id
from failure_advisor import FailureAdvisor, FailureWarning


def _make_store(tmp_path):
    return get_graph_store(tmp_path / "test.db")


def _write_failure(store, project_id, error_type, tool, error_msg, days_ago=1):
    from node_types import create_failure_node, failure_content_id
    node = create_failure_node(project_id, error_type, tool, error_msg)
    # Backdate to desired age
    ts = int(time.time()) - days_ago * 86400
    node.created_at = ts
    node.updated_at = ts
    # Use a unique id per call so duplicates don't deduplicate
    node.id = str(uuid.uuid4())
    store.write_node(node)
    return node


# ── get_failure_trends ────────────────────────────────────────────────────────

def test_trends_groups_by_error_type_and_tool(tmp_path):
    store = _make_store(tmp_path)
    for _ in range(3):
        _write_failure(store, "proj", "adapter_error", "ainl_run", "http failed", days_ago=1)
    trends = store.get_failure_trends("proj", since_days=7, min_count=2)
    assert len(trends) == 1
    assert trends[0]["error_type"] == "adapter_error"
    assert trends[0]["tool"] == "ainl_run"
    assert trends[0]["count"] == 3


def test_trends_respects_min_count(tmp_path):
    store = _make_store(tmp_path)
    _write_failure(store, "proj", "compile_error", "ainl_validate", "bad token", days_ago=1)
    trends = store.get_failure_trends("proj", since_days=7, min_count=2)
    assert len(trends) == 0


def test_trends_respects_since_days(tmp_path):
    store = _make_store(tmp_path)
    for _ in range(3):
        _write_failure(store, "proj", "timeout", "ainl_run", "timed out", days_ago=10)
    trends = store.get_failure_trends("proj", since_days=7, min_count=2)
    assert len(trends) == 0


def test_trends_multiple_clusters(tmp_path):
    store = _make_store(tmp_path)
    for _ in range(3):
        _write_failure(store, "proj", "adapter_error", "ainl_run", "http failed", days_ago=1)
    for _ in range(2):
        _write_failure(store, "proj", "compile_error", "ainl_validate", "bad syntax", days_ago=2)
    trends = store.get_failure_trends("proj", since_days=7, min_count=2)
    assert len(trends) == 2
    # Most frequent first
    assert trends[0]["count"] >= trends[1]["count"]


def test_trends_isolated_by_project(tmp_path):
    store = _make_store(tmp_path)
    for _ in range(3):
        _write_failure(store, "proj_a", "adapter_error", "ainl_run", "fail", days_ago=1)
    trends = store.get_failure_trends("proj_b", since_days=7, min_count=2)
    assert len(trends) == 0


def test_trends_empty_when_no_failures(tmp_path):
    store = _make_store(tmp_path)
    trends = store.get_failure_trends("proj", since_days=7, min_count=2)
    assert trends == []


# ── FailureAdvisor.get_trends ─────────────────────────────────────────────────

def test_advisor_get_trends_returns_list(tmp_path):
    store = _make_store(tmp_path)
    advisor = FailureAdvisor(store, "proj")
    assert isinstance(advisor.get_trends(), list)


def test_advisor_get_trends_delegates_to_store(tmp_path):
    store = _make_store(tmp_path)
    for _ in range(3):
        _write_failure(store, "proj", "runtime_error", "ainl_run", "exec failed", days_ago=1)
    advisor = FailureAdvisor(store, "proj")
    trends = advisor.get_trends(since_days=7, min_count=2)
    assert len(trends) == 1
    assert trends[0]["error_type"] == "runtime_error"


# ── format_warnings with trends ──────────────────────────────────────────────

def test_format_warnings_includes_trend_block(tmp_path):
    store = _make_store(tmp_path)
    advisor = FailureAdvisor(store, "proj")
    trends = [{"error_type": "adapter_error", "tool": "ainl_run", "count": 5, "most_recent": int(time.time())}]
    text = advisor.format_warnings([], trends)
    assert "📈" in text
    assert "adapter_error" in text
    assert "ainl_run" in text
    assert "5" in text


def test_format_warnings_empty_when_no_warnings_or_trends():
    from graph_store import get_graph_store
    # Use in-memory approach
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        store = get_graph_store(Path(td) / "t.db")
        advisor = FailureAdvisor(store, "proj")
        assert advisor.format_warnings([], []) == ""


def test_format_warnings_trends_capped_at_three():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        store = get_graph_store(Path(td) / "t.db")
        advisor = FailureAdvisor(store, "proj")
        trends = [
            {"error_type": f"err_{i}", "tool": "ainl_run", "count": 10 - i, "most_recent": 0}
            for i in range(6)
        ]
        text = advisor.format_warnings([], trends)
        # Only first 3 trend entries rendered
        assert text.count("×") == 0  # no table
        assert text.count("err_0") == 1
        assert text.count("err_3") == 0  # fourth+ not shown
