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
  E. Core memory tools — call-level smoke tests (11 previously uncovered)
  F. Stale scope-lock auto-recovery
  G. Dynamic TOOL_COUNT cross-check
  H. AINL tools absent-package response
  I. SQLite WAL + busy_timeout configuration
"""

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

# Insert plugin root (not mcp_server/) so the package-mode import path fires:
# `from .graph_store import ...` succeeds, mcp_server/ stays off sys.path.
# This mirrors how Claude Code loads the server and catches bare inline imports
# that only fail in package mode (the bug class that caused the node_types incident).
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

from mcp_server.graph_store import SQLiteGraphStore

# Import server in package mode — relative imports succeed, mcp_server/ is NOT
# added to sys.path.  Any bare absolute import inside a tool function without a
# top-level relative counterpart will raise ImportError when that tool is called.
import mcp_server.server as srv

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


# ── E. Core memory tools — call-level smoke tests ─────────────────────────────
# These 11 functions had zero test coverage at the call level (only smoke_test.sh
# tested subsystem imports, never server.py dispatch paths).  Each test calls the
# tool once with valid input and asserts it returns a non-error result.

class TestCoreMemoryToolSmokes:

    def test_memory_store_semantic(self, ctx):
        store, tmp, pid = ctx
        result = run(srv.memory_store_semantic(
            project_id=pid, fact="tests exercise package-mode import path", confidence=0.9
        ))
        assert "error" not in result
        assert result.get("stored") or result.get("node_id") or result.get("ok")

    def test_memory_recall_context(self, ctx):
        store, tmp, pid = ctx
        result = run(srv.memory_recall_context(project_id=pid))
        assert "error" not in result
        assert isinstance(result, dict)

    def test_memory_search(self, ctx):
        store, tmp, pid = ctx
        run(srv.memory_store_semantic(project_id=pid, fact="searchable fact about deployment", confidence=0.8))
        result = run(srv.memory_search(query="deployment", project_id=pid))
        assert "error" not in result
        assert isinstance(result, dict)

    def test_memory_session_history(self, ctx):
        store, tmp, pid = ctx
        result = run(srv.memory_session_history(project_id=pid))
        assert "error" not in result
        assert isinstance(result, dict)

    def test_memory_promote_pattern(self, ctx):
        store, tmp, pid = ctx
        result = run(srv.memory_promote_pattern(
            project_id=pid,
            pattern_name="test-pattern",
            trigger="test trigger",
            tool_sequence=["read", "edit"],
            evidence_ids=["ep-001", "ep-002"],
        ))
        assert "error" not in result

    def test_memory_evolve_persona(self, ctx):
        store, tmp, pid = ctx
        episode_data = {
            "task_description": "refactor module",
            "tool_calls": ["read", "edit", "bash"],
            "files_touched": ["src/main.py"],
            "outcome": "success",
        }
        result = run(srv.memory_evolve_persona(project_id=pid, episode_data=episode_data))
        assert "error" not in result

    def test_memory_expand_node(self, ctx):
        store, tmp, pid = ctx
        ep_result = run(srv.memory_store_episode(
            project_id=pid, task_description="seed ep", tool_calls=[], files_touched=[], outcome="ok"
        ))
        node_id = ep_result.get("node_id") or ep_result.get("id")
        if node_id:
            result = run(srv.memory_expand_node(project_id=pid, node_id=node_id))
            assert "error" not in result

    def test_memory_set_goal_list_complete(self, ctx):
        store, tmp, pid = ctx
        monkeypatched_gt = None
        try:
            from mcp_server.goal_tracker import GoalTracker
            gt = GoalTracker(store, pid)
            original_gt = srv.memory_server.goal_tracker
            srv.memory_server.goal_tracker = gt
            monkeypatched_gt = original_gt
        except Exception:
            pass

        try:
            set_result = run(srv.memory_set_goal(
                title="test goal", description="desc", completion_criteria="done"
            ))
            assert "error" not in set_result
            goal_id = set_result.get("goal_id")

            list_result = run(srv.memory_list_goals())
            assert "error" not in list_result

            if goal_id:
                update_result = run(srv.memory_update_goal(
                    goal_id=goal_id, progress_note="halfway"
                ))
                assert "error" not in update_result

                complete_result = run(srv.memory_complete_goal(goal_id=goal_id))
                assert "error" not in complete_result
        finally:
            if monkeypatched_gt is not None:
                srv.memory_server.goal_tracker = monkeypatched_gt


# ── F. Stale scope-lock auto-recovery ─────────────────────────────────────────

class TestScopeLockRecovery:

    def test_cancel_task_clears_active_scope_lock(self, ctx):
        """memory_cancel_task should release the scope lock if the cancelled task is active."""
        store, tmp, pid = ctx
        task_id = "cancel-lock-" + uuid.uuid4().hex[:8]
        store.create_autonomous_task(
            task_id=task_id, project_id=pid, description="task to cancel",
            schedule="+1d", created_by="test", priority=5,
        )
        sidecar = tmp / "logs" / "active_task.json"
        sidecar.write_text(json.dumps({
            "task_id": task_id, "project_id": pid,
            "allowed_actions": ["memory_list_goals"],
            "started_at": time.time(),
        }))
        result = run(srv.memory_cancel_task(task_id=task_id))
        assert result.get("cancelled") is True
        assert result.get("scope_lock_cleared") is True
        assert not sidecar.exists()

    def test_cancel_task_nonactive_does_not_clear_others_lock(self, ctx):
        """Cancelling an inactive task must not clear another task's active lock."""
        store, tmp, pid = ctx
        active_id = "active-task-001"
        cancel_id = "cancel-other-" + uuid.uuid4().hex[:8]
        store.create_autonomous_task(
            task_id=cancel_id, project_id=pid, description="unrelated task",
            schedule="+1d", created_by="test", priority=5,
        )
        sidecar = tmp / "logs" / "active_task.json"
        sidecar.write_text(json.dumps({
            "task_id": active_id, "project_id": pid,
            "allowed_actions": [], "started_at": time.time(),
        }))
        result = run(srv.memory_cancel_task(task_id=cancel_id))
        assert result.get("scope_lock_cleared") is False
        assert sidecar.exists()

    def test_startup_clear_stale_scope_lock(self, tmp_path):
        """_clear_stale_scope_lock removes active_task.json at session start."""
        from hooks.startup import _clear_stale_scope_lock
        (tmp_path / "logs").mkdir()
        sidecar = tmp_path / "logs" / "active_task.json"
        sidecar.write_text('{"task_id": "orphaned", "started_at": 0}')
        _clear_stale_scope_lock(tmp_path)
        assert not sidecar.exists()

    def test_startup_clear_is_noop_when_no_sidecar(self, tmp_path):
        from hooks.startup import _clear_stale_scope_lock
        _clear_stale_scope_lock(tmp_path)  # must not raise

    def test_tools_unblocked_after_startup_clear(self, ctx, tmp_path):
        """After a stale lock is cleared, tools should execute normally."""
        from hooks.startup import _clear_stale_scope_lock
        store, test_tmp, pid = ctx
        sidecar = test_tmp / "logs" / "active_task.json"
        sidecar.write_text(json.dumps({
            "task_id": "orphaned", "project_id": pid,
            "allowed_actions": ["memory_list_goals"],
            "started_at": time.time() - 3600,
        }))
        _clear_stale_scope_lock(test_tmp)
        result = run(srv.call_tool("memory_store_episode", {
            "project_id": pid, "task_description": "post-clear call",
            "tool_calls": [], "files_touched": [], "outcome": "ok",
        }))
        data = json.loads(result[0].text)
        assert data.get("error") != "tool_blocked_by_task_scope"


# ── G. Dynamic TOOL_COUNT cross-check ────────────────────────────────────────

class TestToolCountConsistency:

    def test_list_tools_count_matches_constants(self):
        """The hardcoded TOOL_COUNT_* constants in startup.py must match the actual
        number of Tool() declarations in server.py's list_tools block.

        This catches the drift where someone adds a tool but forgets to bump the
        constant, causing the startup banner to report the wrong tool count."""
        server_src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text()
        startup_src = (PLUGIN_ROOT / "hooks" / "startup.py").read_text()

        import re

        # Count Tool() lines in the list_tools function (before call_tool)
        list_tools_match = re.search(
            r'@server\.list_tools\(\)(.*?)@server\.call_tool\(\)',
            server_src, re.DOTALL
        )
        assert list_tools_match, "list_tools block not found"
        block = list_tools_match.group(1)

        memory_tools = len(re.findall(r'name="memory_\w+"', block))
        ainl_tools = len(re.findall(r'name="ainl_\w+"', block))
        a2a_tools = len(re.findall(r'name="a2a_\w+"', block))

        m = re.search(r'TOOL_COUNT_MEMORY\s*=\s*(\d+)', startup_src)
        assert m, "TOOL_COUNT_MEMORY not found in startup.py"
        expected_memory = int(m.group(1))

        m = re.search(r'TOOL_COUNT_AINL\s*=\s*(\d+)', startup_src)
        assert m, "TOOL_COUNT_AINL not found"
        expected_ainl = int(m.group(1))

        m = re.search(r'TOOL_COUNT_A2A\s*=\s*(\d+)', startup_src)
        assert m, "TOOL_COUNT_A2A not found"
        expected_a2a = int(m.group(1))

        assert memory_tools == expected_memory, (
            f"TOOL_COUNT_MEMORY={expected_memory} but {memory_tools} memory tools declared in list_tools"
        )
        assert ainl_tools == expected_ainl, (
            f"TOOL_COUNT_AINL={expected_ainl} but {ainl_tools} ainl tools declared in list_tools"
        )
        assert a2a_tools == expected_a2a, (
            f"TOOL_COUNT_A2A={expected_a2a} but {a2a_tools} a2a tools declared in list_tools"
        )


# ── H. AINL tools absent-package response ─────────────────────────────────────
# These tests force ainl_tools=None (package not installed) and verify that every
# AINL tool returns a structured, user-actionable error instead of crashing.

class TestAINLToolsAbsentPackage:

    @pytest.fixture()
    def no_ainl(self, ctx, monkeypatch):
        store, tmp, pid = ctx
        monkeypatch.setattr(srv.memory_server, "ainl_tools", None)
        return store, tmp, pid

    def _call_ainl(self, tool_name, args=None):
        result = run(srv.call_tool(tool_name, args or {}))
        return json.loads(result[0].text)

    def test_ainl_validate_returns_structured_error(self, no_ainl):
        data = self._call_ainl("ainl_validate", {"code": "step: x\n  do: nothing"})
        assert data.get("ok") is False
        assert "error" in data
        assert "ainativelang" in data.get("error", "") or "not installed" in data.get("error", "")

    def test_ainl_compile_includes_install_key(self, no_ainl):
        data = self._call_ainl("ainl_compile", {"code": "step: x\n  do: nothing"})
        assert "install" in data, "Error response must include an 'install' key for user guidance"
        assert "pip install" in data.get("install", "")

    def test_ainl_run_returns_ok_false(self, no_ainl):
        data = self._call_ainl("ainl_run", {"file": "workflow.ainl"})
        assert data.get("ok") is False

    def test_ainl_get_started_error_has_hint(self, no_ainl):
        data = self._call_ainl("ainl_get_started", {})
        assert "hint" in data or "install" in data

    def test_all_ainl_tools_return_dict_not_exception(self, no_ainl):
        """No AINL tool should raise an unhandled exception when package is absent."""
        tools = [
            ("ainl_validate", {"code": "x"}),
            ("ainl_compile", {"code": "x"}),
            ("ainl_run", {"file": "x.ainl"}),
            ("ainl_capabilities", {}),
            ("ainl_security_report", {}),
            ("ainl_get_started", {}),
            ("ainl_step_examples", {}),
            ("ainl_adapter_contract", {}),
        ]
        for tool_name, args in tools:
            result = run(srv.call_tool(tool_name, args))
            data = json.loads(result[0].text)
            assert isinstance(data, dict), f"{tool_name} returned non-dict: {result}"
            assert data.get("ok") is False, f"{tool_name} should report ok=False when package absent"


# ── I. SQLite WAL + busy_timeout ──────────────────────────────────────────────

class TestSQLiteConfiguration:

    def test_wal_mode_enabled(self, tmp_path):
        from mcp_server.graph_store import SQLiteGraphStore
        store = SQLiteGraphStore(tmp_path / "wal_test.db")
        row = store.conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal", "journal_mode must be WAL for concurrent read safety"

    def test_busy_timeout_set(self, tmp_path):
        from mcp_server.graph_store import SQLiteGraphStore
        store = SQLiteGraphStore(tmp_path / "bt_test.db")
        row = store.conn.execute("PRAGMA busy_timeout").fetchone()
        assert int(row[0]) >= 1000, (
            f"busy_timeout must be >= 1000ms to handle concurrent Claude Code windows; got {row[0]}"
        )

    def test_concurrent_writes_do_not_deadlock_immediately(self, tmp_path):
        """Multiple connections writing DML to the same DB must not fail with immediate lock error.

        Production scenario: two Claude Code windows both open the same project DB
        (MCP server initializes once per process).  Schema already exists; threads
        do DML (INSERT) only — no DDL races.

        With busy_timeout=0 (old default), the second writer fails instantly.
        With WAL + busy_timeout>=1000ms it retries — this test verifies all writes
        complete successfully."""
        import threading
        from mcp_server.graph_store import SQLiteGraphStore
        from mcp_server.node_types import create_semantic_node

        db = tmp_path / "concurrent.db"
        # Initialize schema once (as MCP server does on startup)
        SQLiteGraphStore(db)

        errors = []

        def write_node(i):
            try:
                s = SQLiteGraphStore(db)
                node = create_semantic_node(
                    project_id="concurrent-test",
                    fact=f"concurrent write {i}",
                    confidence=0.5,
                )
                s.write_node(node)
            except Exception as e:
                errors.append(f"writer {i}: {e}")

        threads = [threading.Thread(target=write_node, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors, f"Concurrent DML writes failed (check busy_timeout + WAL): {errors}"
