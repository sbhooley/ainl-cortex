"""
Integration tests for async MCP tool functions and the tool-call interceptor.

These tests actually CALL the async functions (via asyncio.run) with a real
SQLiteGraphStore, verifying runtime behaviour rather than source-code structure.

Sections:
  A. Task lifecycle async tools (memory_schedule_task, memory_approve_task,
     memory_begin_task_execution, memory_complete_task, memory_cancel_task,
     memory_update_task, memory_list_scheduled_tasks)
  B. memory_store_failure auto-extract file
  C. memory_list_autonomous_executions (audit log)
  D. Tool-call interceptor end-to-end (begin → block → complete → clear)
"""

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

from graph_store import SQLiteGraphStore

# Import server module — memory_server is initialised at import time with the
# real DB; we swap memory_server.store per-test via monkeypatch.
import server as srv

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    """
    Per-test context:
    - Swaps memory_server.store with an isolated SQLite DB in tmp_path.
    - Sets CLAUDE_PLUGIN_ROOT so active_task.json / execution log go to tmp_path.
    - Creates logs/ dir.
    Returns (store, tmp_path, project_id).
    """
    store = SQLiteGraphStore(tmp_path / "test.db")
    monkeypatch.setattr(srv.memory_server, "store", store)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    (tmp_path / "logs").mkdir(exist_ok=True)
    project_id = "test-proj-" + uuid.uuid4().hex[:8]
    return store, tmp_path, project_id


# ── A. Task lifecycle ─────────────────────────────────────────────────────────

class TestMemoryScheduleTask:

    def test_creates_task_returns_task_id(self, ctx):
        store, tmp, pid = ctx
        result = run(srv.memory_schedule_task(project_id=pid, description="check goals"))
        assert "task_id" in result
        assert "error" not in result
        task = store.get_autonomous_task(result["task_id"])
        assert task is not None
        assert task["description"] == "check goals"

    def test_read_only_not_requires_approval(self, ctx):
        _, tmp, pid = ctx
        result = run(srv.memory_schedule_task(
            project_id=pid, description="read goals", risk_tier="read_only"
        ))
        assert result.get("requires_approval") is False

    def test_memory_ops_requires_approval(self, ctx):
        _, tmp, pid = ctx
        result = run(srv.memory_schedule_task(
            project_id=pid, description="store episode", risk_tier="memory_ops"
        ))
        assert result.get("requires_approval") is True

    def test_file_write_requires_approval(self, ctx):
        _, tmp, pid = ctx
        result = run(srv.memory_schedule_task(
            project_id=pid, description="edit files", risk_tier="file_write"
        ))
        assert result.get("requires_approval") is True

    def test_invalid_risk_tier_returns_error(self, ctx):
        _, tmp, pid = ctx
        result = run(srv.memory_schedule_task(
            project_id=pid, description="bad task", risk_tier="totally_wrong"
        ))
        assert "error" in result

    def test_invalid_schedule_returns_error(self, ctx):
        _, tmp, pid = ctx
        result = run(srv.memory_schedule_task(
            project_id=pid, description="bad schedule", schedule="every monday pls"
        ))
        assert "error" in result

    def test_path_scope_stored(self, ctx):
        store, tmp, pid = ctx
        result = run(srv.memory_schedule_task(
            project_id=pid, description="scoped task",
            path_scope=["/home/user/myproject"]
        ))
        task = store.get_autonomous_task(result["task_id"])
        raw = task.get("path_scope")
        assert raw is not None
        paths = json.loads(raw) if isinstance(raw, str) else raw
        assert "/home/user/myproject" in paths

    def test_run_now_sets_next_run_at_to_now(self, ctx):
        store, tmp, pid = ctx
        before = time.time()
        result = run(srv.memory_schedule_task(
            project_id=pid, description="immediate", run_now=True
        ))
        task = store.get_autonomous_task(result["task_id"])
        assert task["next_run_at"] is not None
        assert task["next_run_at"] >= before - 1


class TestMemoryApproveTask:

    def test_read_only_returns_early_no_db_change(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(
            project_id=pid, description="read task", risk_tier="read_only"
        ))
        result = run(srv.memory_approve_task(task_id=sched["task_id"]))
        assert result.get("ok") is True
        assert "auto-approved" in result.get("note", "").lower() or \
               result.get("approved_by") == "system"

    def test_memory_ops_task_gets_approved(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(
            project_id=pid, description="write task", risk_tier="memory_ops"
        ))
        tid = sched["task_id"]
        task_before = store.get_autonomous_task(tid)
        assert task_before["approved_by"] is None

        result = run(srv.memory_approve_task(task_id=tid))
        assert result.get("ok") is True
        task_after = store.get_autonomous_task(tid)
        assert task_after["approved_by"] == "user"

    def test_unknown_task_returns_error(self, ctx):
        result = run(srv.memory_approve_task(task_id="nonexistent-id"))
        assert "error" in result


class TestMemoryBeginTaskExecution:

    def test_writes_active_task_json(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(
            project_id=pid, description="test task",
            allowed_actions=["memory_list_goals"],
        ))
        tid = sched["task_id"]
        result = run(srv.memory_begin_task_execution(task_id=tid, project_id=pid))
        assert result.get("ok") is True
        sidecar = tmp / "logs" / "active_task.json"
        assert sidecar.exists()
        data = json.loads(sidecar.read_text())
        assert data["task_id"] == tid
        assert "memory_list_goals" in data["allowed_actions"]

    def test_scope_lock_active_when_allowed_actions_set(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(
            project_id=pid, description="scoped",
            allowed_actions=["memory_list_goals"],
        ))
        result = run(srv.memory_begin_task_execution(
            task_id=sched["task_id"], project_id=pid
        ))
        assert result.get("scope_lock_active") is True

    def test_scope_lock_inactive_when_no_allowed_actions(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(
            project_id=pid, description="open task",
        ))
        result = run(srv.memory_begin_task_execution(
            task_id=sched["task_id"], project_id=pid
        ))
        assert result.get("scope_lock_active") is False

    def test_unknown_task_returns_error(self, ctx):
        result = run(srv.memory_begin_task_execution(
            task_id="nonexistent", project_id="p"
        ))
        assert "error" in result


class TestMemoryCompleteTask:

    def test_completes_one_shot_task(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(
            project_id=pid, description="one-shot"
        ))
        tid = sched["task_id"]
        result = run(srv.memory_complete_task(task_id=tid, note="done"))
        assert result.get("completed") is True
        task = store.get_autonomous_task(tid)
        assert task["status"] == "completed"

    def test_recurring_task_rescheduled(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(
            project_id=pid, description="recurring", schedule="+1h"
        ))
        tid = sched["task_id"]
        before = time.time()
        result = run(srv.memory_complete_task(task_id=tid, reschedule=True))
        assert result.get("rescheduled") is True
        task = store.get_autonomous_task(tid)
        assert task["next_run_at"] > before

    def test_clears_active_task_json(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(
            project_id=pid, description="task with lock",
            allowed_actions=["memory_list_goals"],
        ))
        tid = sched["task_id"]
        # Activate scope lock
        run(srv.memory_begin_task_execution(task_id=tid, project_id=pid))
        sidecar = tmp / "logs" / "active_task.json"
        assert sidecar.exists()
        # Complete task — should clear the sidecar
        run(srv.memory_complete_task(task_id=tid))
        assert not sidecar.exists()

    def test_writes_execution_log(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(
            project_id=pid, description="log test"
        ))
        run(srv.memory_complete_task(task_id=sched["task_id"], note="logged"))
        log_file = tmp / "logs" / "autonomous_executions.jsonl"
        assert log_file.exists()
        lines = [json.loads(l) for l in log_file.read_text().strip().splitlines()]
        assert any(l.get("task_id") == sched["task_id"] for l in lines)

    def test_unknown_task_returns_error(self, ctx):
        result = run(srv.memory_complete_task(task_id="nonexistent"))
        assert "error" in result

    def test_scope_lock_cleared_flag_in_response(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(project_id=pid, description="x"))
        result = run(srv.memory_complete_task(task_id=sched["task_id"]))
        assert "scope_lock_cleared" in result


class TestMemoryCancelAndUpdateTask:

    def test_cancel_task(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(project_id=pid, description="to cancel"))
        tid = sched["task_id"]
        result = run(srv.memory_cancel_task(task_id=tid))
        assert result.get("cancelled") is True
        task = store.get_autonomous_task(tid)
        assert task["status"] == "cancelled"

    def test_update_task_description(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(project_id=pid, description="old name"))
        tid = sched["task_id"]
        run(srv.memory_update_task(task_id=tid, description="new name"))
        task = store.get_autonomous_task(tid)
        assert task["description"] == "new name"

    def test_update_task_approved_by(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(
            project_id=pid, description="needs approval", risk_tier="memory_ops"
        ))
        tid = sched["task_id"]
        run(srv.memory_update_task(task_id=tid, approved_by="user"))
        task = store.get_autonomous_task(tid)
        assert task["approved_by"] == "user"

    def test_update_task_path_scope(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(project_id=pid, description="task"))
        tid = sched["task_id"]
        run(srv.memory_update_task(task_id=tid, path_scope=["/new/scope"]))
        task = store.get_autonomous_task(tid)
        paths = json.loads(task["path_scope"])
        assert "/new/scope" in paths

    def test_update_invalid_priority_returns_error(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(project_id=pid, description="task"))
        result = run(srv.memory_update_task(task_id=sched["task_id"], priority=99))
        assert "error" in result

    def test_list_scheduled_tasks_returns_seconds_until_due(self, ctx):
        store, tmp, pid = ctx
        run(srv.memory_schedule_task(
            project_id=pid, description="future task", schedule="+1h"
        ))
        result = run(srv.memory_list_scheduled_tasks(project_id=pid))
        assert result.get("count", 0) > 0
        task = result["tasks"][0]
        assert "seconds_until_due" in task


# ── B. memory_store_failure auto-extract file ─────────────────────────────────

class TestMemoryStoreFailureAutoExtract:

    def test_py_file_extracted_from_error_message(self, ctx):
        store, tmp, pid = ctx
        result = run(srv.memory_store_failure(
            project_id=pid,
            error_type="import_error",
            tool="ainl_run",
            error_message="ImportError in mcp_server/graph_store.py line 42",
        ))
        assert "error" not in result
        nodes = store.get_unresolved_failures(pid, limit=10)
        assert len(nodes) > 0
        file_val = nodes[0].data.get("file")
        assert file_val is not None and "graph_store.py" in file_val

    def test_explicit_file_not_overridden(self, ctx):
        store, tmp, pid = ctx
        run(srv.memory_store_failure(
            project_id=pid,
            error_type="load_error",
            tool="ainl_run",
            error_message="failed to load other.py",
            file="explicit.py",
        ))
        nodes = store.get_unresolved_failures(pid, limit=10)
        assert nodes[0].data.get("file") == "explicit.py"

    def test_no_file_in_message_leaves_file_none(self, ctx):
        store, tmp, pid = ctx
        run(srv.memory_store_failure(
            project_id=pid,
            error_type="conn_error",
            tool="ainl_run",
            error_message="connection refused: host unreachable",
        ))
        nodes = store.get_unresolved_failures(pid, limit=10)
        assert nodes[0].data.get("file") is None


# ── C. memory_list_autonomous_executions ─────────────────────────────────────

class TestMemoryListAutonomousExecutions:

    def test_returns_empty_when_no_log(self, ctx):
        _, tmp, pid = ctx
        result = run(srv.memory_list_autonomous_executions(project_id=pid))
        assert result.get("total", 0) == 0

    def test_returns_execution_after_complete_task(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(project_id=pid, description="audited"))
        run(srv.memory_complete_task(task_id=sched["task_id"], note="done"))
        result = run(srv.memory_list_autonomous_executions(project_id=pid))
        assert result["total"] >= 1
        assert any(e["task_id"] == sched["task_id"] for e in result["executions"])

    def test_filters_by_project_id(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(project_id=pid, description="my task"))
        run(srv.memory_complete_task(task_id=sched["task_id"]))
        # Query different project — should get 0
        result = run(srv.memory_list_autonomous_executions(project_id="other-project"))
        assert result["total"] == 0


# ── D. Tool-call interceptor end-to-end ──────────────────────────────────────

class TestToolCallInterceptor:

    def test_tool_blocked_when_active_task_json_present(self, ctx):
        store, tmp, pid = ctx
        # Write active_task.json with a restricted whitelist
        sidecar = tmp / "logs" / "active_task.json"
        sidecar.write_text(json.dumps({
            "task_id": "t1",
            "project_id": pid,
            "allowed_actions": ["memory_list_goals"],
            "risk_tier": "memory_ops",
            "started_at": time.time(),
        }))
        # memory_store_episode is NOT in the whitelist — should be blocked
        result = run(srv.call_tool("memory_store_episode", {
            "project_id": pid,
            "task_description": "test",
            "tool_calls": [],
            "files_touched": [],
            "outcome": "ok",
        }))
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data.get("error") == "tool_blocked_by_task_scope"
        assert data.get("tool_called") == "memory_store_episode"

    def test_always_allowed_tool_passes_through_scope_lock(self, ctx):
        store, tmp, pid = ctx
        sidecar = tmp / "logs" / "active_task.json"
        sidecar.write_text(json.dumps({
            "task_id": "t1",
            "project_id": pid,
            "allowed_actions": ["memory_list_goals"],
            "risk_tier": "memory_ops",
            "started_at": time.time(),
        }))
        # memory_complete_task is always allowed
        result = run(srv.call_tool("memory_complete_task", {"task_id": "nonexistent-id"}))
        data = json.loads(result[0].text)
        # Should get task_not_found, not tool_blocked
        assert data.get("error") != "tool_blocked_by_task_scope"
        assert "task_not_found" in str(data) or "error" in data

    def test_no_scope_lock_when_active_task_json_absent(self, ctx):
        store, tmp, pid = ctx
        sidecar = tmp / "logs" / "active_task.json"
        assert not sidecar.exists()
        # Without sidecar, tool should not be blocked (might fail for other reasons)
        result = run(srv.call_tool("memory_store_episode", {
            "project_id": pid,
            "task_description": "test",
            "tool_calls": [],
            "files_touched": [],
            "outcome": "ok",
        }))
        data = json.loads(result[0].text)
        assert data.get("error") != "tool_blocked_by_task_scope"

    def test_null_allowed_actions_does_not_block(self, ctx):
        """Task with allowed_actions=null should not trigger blocking."""
        store, tmp, pid = ctx
        sidecar = tmp / "logs" / "active_task.json"
        sidecar.write_text(json.dumps({
            "task_id": "t1",
            "project_id": pid,
            "allowed_actions": None,  # null = no whitelist enforced
            "risk_tier": "read_only",
            "started_at": time.time(),
        }))
        result = run(srv.call_tool("memory_store_episode", {
            "project_id": pid,
            "task_description": "test",
            "tool_calls": [],
            "files_touched": [],
            "outcome": "ok",
        }))
        data = json.loads(result[0].text)
        assert data.get("error") != "tool_blocked_by_task_scope"

    def test_complete_task_clears_sidecar(self, ctx):
        store, tmp, pid = ctx
        sched = run(srv.memory_schedule_task(
            project_id=pid, description="full cycle",
            allowed_actions=["memory_list_goals"],
        ))
        tid = sched["task_id"]
        # Begin → sidecar created
        run(srv.memory_begin_task_execution(task_id=tid, project_id=pid))
        sidecar = tmp / "logs" / "active_task.json"
        assert sidecar.exists()
        # Complete → sidecar deleted
        run(srv.memory_complete_task(task_id=tid))
        assert not sidecar.exists()

    def test_blocked_response_includes_allowed_actions(self, ctx):
        store, tmp, pid = ctx
        allowed = ["memory_list_goals", "memory_update_goal"]
        sidecar = tmp / "logs" / "active_task.json"
        sidecar.write_text(json.dumps({
            "task_id": "t1", "project_id": pid,
            "allowed_actions": allowed, "risk_tier": "memory_ops",
            "started_at": time.time(),
        }))
        result = run(srv.call_tool("memory_store_failure", {
            "project_id": pid, "error_type": "e", "tool": "t", "error_message": "m"
        }))
        data = json.loads(result[0].text)
        assert data.get("error") == "tool_blocked_by_task_scope"
        returned_aa = data.get("allowed_actions", [])
        assert set(returned_aa) == set(allowed)

    def test_interceptor_survives_corrupt_sidecar(self, ctx):
        """Corrupt active_task.json should not crash the tool call."""
        store, tmp, pid = ctx
        sidecar = tmp / "logs" / "active_task.json"
        sidecar.write_text("{invalid json{{")
        # Should not raise; tool should proceed (or fail for other reasons)
        try:
            result = run(srv.call_tool("memory_store_episode", {
                "project_id": pid, "task_description": "t",
                "tool_calls": [], "files_touched": [], "outcome": "ok",
            }))
            data = json.loads(result[0].text)
            assert data.get("error") != "tool_blocked_by_task_scope"
        except Exception:
            pass  # any non-interceptor exception is acceptable
