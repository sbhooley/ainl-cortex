"""Verify A2A tools are advertised + dispatched only when enabled in config.

Covers Issue B1 from the post-fix audit. Two regression scenarios:

1. ``config.a2a.enabled = False`` → no tool whose name starts with ``a2a_``
   appears in ``list_tools`` output, and a direct ``call_tool`` dispatch for
   one of those names returns a structured ``feature_disabled`` envelope
   rather than 500-ing or silently executing.
2. ``config.a2a.enabled = True`` → all 7 a2a tools are advertised.

The test mutates ``memory_server._a2a_enabled`` directly (post-init) instead
of reconstructing the server, because ``AINLGraphMemoryServer.__init__``
loads config from ``config.json`` on disk and we want a hermetic test.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "mcp_server"))


def _import_server():
    import server as srv  # type: ignore
    return srv


def _list_tools_sync(srv) -> list:
    return asyncio.run(srv.list_tools())


def _call_tool_sync(srv, name: str, args: dict) -> list:
    return asyncio.run(srv.call_tool(name, args))


_A2A_NAMES = {
    "a2a_send",
    "a2a_list_agents",
    "a2a_register_agent",
    "a2a_note_to_self",
    "a2a_register_monitor",
    "a2a_task_send",
    "a2a_task_status",
}


def test_a2a_tools_hidden_when_disabled():
    srv = _import_server()
    srv.memory_server._a2a_enabled = False

    advertised = {t.name for t in _list_tools_sync(srv)}
    assert advertised.isdisjoint(_A2A_NAMES), (
        f"A2A tools must not be advertised when disabled, got: "
        f"{sorted(advertised & _A2A_NAMES)}"
    )


def test_a2a_call_tool_returns_feature_disabled_when_off():
    srv = _import_server()
    srv.memory_server._a2a_enabled = False

    result = _call_tool_sync(srv, "a2a_list_agents", {})
    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload["ok"] is False
    assert payload["error_type"] == "feature_disabled"


def test_a2a_tools_advertised_when_enabled():
    srv = _import_server()
    srv.memory_server._a2a_enabled = True

    advertised = {t.name for t in _list_tools_sync(srv)}
    missing = _A2A_NAMES - advertised
    assert not missing, f"Expected a2a tools advertised when enabled, missing: {sorted(missing)}"


# ── a2a_task_status regression: failed tasks with error must be marked failed ──

import json
import time
import types
import tempfile
import unittest.mock
from pathlib import Path

def _make_a2a_tools(tmp_path: Path):
    """Construct a minimal A2ATools instance with a temp plugin root."""
    sys.path.insert(0, str(PLUGIN_ROOT / "mcp_server"))
    from a2a_tools import A2ATools
    from graph_store import get_graph_store

    db = tmp_path / "test.db"
    store = get_graph_store(db)
    tools = A2ATools(
        plugin_root=tmp_path,
        store=store,
        project_id="test-proj",
        config={},
    )
    return tools


def _write_task_file(tasks_dir: Path, task_id: str, armaraos_task_id: str) -> None:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / f"{task_id}.json").write_text(json.dumps({
        "task_id": task_id,
        "armaraos_task_id": armaraos_task_id,
        "to_agent": "other-agent",
        "agent_id": "agent-uuid",
        "task_description": "test task",
        "callback_urgency": "normal",
        "status": "pending",
        "created_at": int(time.time()),
        "completed_at": None,
        "result": None,
        "node_id": "node-1",
        "send_error": None,
    }))


def test_a2a_task_status_marks_failed_when_error_present(tmp_path):
    """Regression: a failed task whose ArmaraOS response carries an 'error' key
    must be marked as failed — not left as 'pending' forever.

    The pre-fix logic had ``elif remote_status in ('cancelled', 'failed') and
    'error' not in remote`` which meant tasks with error details were never
    updated.
    """
    tools = _make_a2a_tools(tmp_path)
    task_id = "task-regression-1"
    armaraos_id = "arm-task-001"
    _write_task_file(tools.tasks_dir, task_id, armaraos_id)

    # Mock _a2a_client so it returns a failed response WITH an error key
    fake_remote = {"status": "failed", "error": "executor timeout"}

    def fake_client():
        # Returns (send_to_agent, list_agents, get_card, is_alive, get_task_status, discover)
        return (None, None, None, None, lambda tid, **kw: fake_remote, None)

    import a2a_tools as _a2a_mod
    with unittest.mock.patch.object(_a2a_mod, "_a2a_client", fake_client):
        result = tools.a2a_task_status(task_id)

    assert result["status"] == "failed", (
        f"Task with remote status=failed and error key must be marked failed, got: {result['status']!r}"
    )
    assert result.get("send_error") == "executor timeout"
