"""MCP dispatch tests for cost-control tools (via ``call_tool``)."""

import json
import uuid
from pathlib import Path

import pytest

import mcp_server.server as srv
from mcp_server.graph_store import SQLiteGraphStore
from mcp_server.node_types import NodeType, create_procedural_node
from mcp_server.tool_digest import store_tool_outcome_blob

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def run(coro):
    import asyncio

    return asyncio.run(coro)


def _parse(result):
    return json.loads(result[0].text)


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "test.db")
    monkeypatch.setattr(srv.memory_server, "store", store)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    (tmp_path / "logs").mkdir(exist_ok=True)
    project_id = "cost-mcp-" + uuid.uuid4().hex[:8]
    return store, tmp_path, project_id


class TestCortexCostSnapshotMcp:

    def test_call_tool_returns_session_and_project_keys(self, ctx):
        _, tmp, pid = ctx
        metrics = tmp / "logs" / "hook_metrics.jsonl"
        metrics.write_text(
            json.dumps(
                {
                    "hook": "recall_cycle",
                    "project_id": pid,
                    "recall_skips": 1,
                    "compression_saved_tokens_est": 42,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        data = _parse(
            run(
                srv.call_tool(
                    "cortex_cost_snapshot",
                    {"project_id": pid, "session_hours": 24, "project_days": 7},
                )
            )
        )
        assert "session" in data
        assert "project" in data
        assert data["project"].get("project_id") == pid


class TestMemoryGetToolOutcomeMcp:

    def test_round_trip_blob(self, ctx, monkeypatch):
        _, tmp, pid = ctx
        monkeypatch.setenv("HOME", str(tmp))
        blob_id = "blob-" + uuid.uuid4().hex[:8]
        store_tool_outcome_blob(PLUGIN_ROOT, pid, blob_id, "full tool output text")
        data = _parse(
            run(
                srv.call_tool(
                    "memory_get_tool_outcome",
                    {"project_id": pid, "blob_id": blob_id},
                )
            )
        )
        assert data.get("ok") is True
        assert "full tool output" in data.get("text", "")

    def test_missing_blob(self, ctx):
        _, _, pid = ctx
        data = _parse(
            run(
                srv.call_tool(
                    "memory_get_tool_outcome",
                    {"project_id": pid, "blob_id": "does-not-exist"},
                )
            )
        )
        assert data.get("ok") is False


class TestAinlPromotePatternMcp:

    def test_dispatched_when_ainl_tools_present(self, ctx, monkeypatch):
        store, _, pid = ctx
        called = {}

        class _Stub:
            def promote_pattern(self, **kwargs):
                called.update(kwargs)
                return {"ok": True, "stub": True}

        monkeypatch.setattr(srv.memory_server, "ainl_tools", _Stub())
        data = _parse(
            run(
                srv.call_tool(
                    "ainl_promote_pattern",
                    {"project_id": pid, "pattern_name": "demo_flow"},
                )
            )
        )
        assert data.get("ok") is True
        assert called.get("project_id") == pid
