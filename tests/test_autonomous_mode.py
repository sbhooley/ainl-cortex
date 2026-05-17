"""
Tests for the autonomous mode feature:
  A. Schedule expression parser (autonomous_scheduler.py)
  B. DB CRUD — create / list / get / update / cancel
  C. mark_task_run — one-shot completion, recurring reschedule, max_runs
  D. due_only filtering and priority ordering
  E. NativeGraphStore delegation (source-code check)
  F. MCP tool schema validation (server.py source checks)
  G. Startup hook injection (source-code checks)
  H. Config section validation
  I. Server dispatch registration
  J. Edge cases — invalid schedule, unknown task_id, bad priority
"""

import sys
import json
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# ── A. Schedule parser ────────────────────────────────────────────────────────

from autonomous_scheduler import parse_next_run, is_valid_schedule, describe_schedule


class TestScheduleParser:

    def test_relative_minutes(self):
        now = time.time()
        result = parse_next_run("+30m", since=now)
        assert abs(result - (now + 1800)) < 1

    def test_relative_hours(self):
        now = time.time()
        result = parse_next_run("+6h", since=now)
        assert abs(result - (now + 6 * 3600)) < 1

    def test_relative_days(self):
        now = time.time()
        result = parse_next_run("+1d", since=now)
        assert abs(result - (now + 86400)) < 1

    def test_relative_weeks(self):
        now = time.time()
        result = parse_next_run("+2w", since=now)
        assert abs(result - (now + 2 * 86400 * 7)) < 1

    def test_relative_case_insensitive(self):
        now = time.time()
        assert abs(parse_next_run("+1H", since=now) - (now + 3600)) < 1

    def test_named_hourly(self):
        now = time.time()
        result = parse_next_run("@hourly", since=now)
        assert abs(result - (now + 3600)) < 1

    def test_named_daily(self):
        now = time.time()
        result = parse_next_run("@daily", since=now)
        assert abs(result - (now + 86400)) < 1

    def test_named_weekly(self):
        now = time.time()
        result = parse_next_run("@weekly", since=now)
        assert abs(result - (now + 86400 * 7)) < 1

    def test_named_monthly(self):
        now = time.time()
        result = parse_next_run("@monthly", since=now)
        assert abs(result - (now + 86400 * 30)) < 1

    def test_cron_wildcard_all(self):
        """'* * * * *' fires at the next minute."""
        now = time.time()
        result = parse_next_run("* * * * *", since=now)
        assert result > now
        assert result - now <= 120  # within 2 minutes

    def test_cron_fixed_minute(self):
        """'0 * * * *' fires at the next top-of-hour."""
        now = time.time()
        result = parse_next_run("0 * * * *", since=now)
        lt = time.localtime(result)
        assert lt.tm_min == 0

    def test_cron_fixed_hour_and_minute(self):
        """'30 14 * * *' fires at 14:30."""
        now = time.time()
        result = parse_next_run("30 14 * * *", since=now)
        lt = time.localtime(result)
        assert lt.tm_min == 30
        assert lt.tm_hour == 14

    def test_cron_result_is_after_since(self):
        now = time.time()
        result = parse_next_run("* * * * *", since=now)
        assert result > now

    def test_cron_weekday_zero_is_sunday(self):
        """Weekday 0 in the cron convention maps to Sunday."""
        now = time.time()
        result = parse_next_run("0 12 * * 0", since=now)  # noon on Sunday
        lt = time.localtime(result)
        assert lt.tm_hour == 12
        assert lt.tm_min == 0
        # tm_wday in Python: 6=Sunday; cron 0=Sunday → after convert (wday+1)%7
        assert (lt.tm_wday + 1) % 7 == 0

    def test_default_since_is_now(self):
        before = time.time()
        result = parse_next_run("+1h")
        after = time.time()
        assert before + 3600 <= result <= after + 3600 + 1

    def test_invalid_expression_raises(self):
        with pytest.raises(ValueError):
            parse_next_run("every monday")

    def test_invalid_cron_field_out_of_range(self):
        with pytest.raises(ValueError):
            parse_next_run("60 25 * * *")  # minute=60, hour=25

    def test_invalid_cron_wrong_field_count(self):
        with pytest.raises(ValueError):
            parse_next_run("0 9 * *")  # only 4 fields

    def test_is_valid_schedule_true(self):
        for expr in ["+1h", "+1d", "@daily", "@weekly", "0 9 * * 1", "* * * * *"]:
            assert is_valid_schedule(expr), f"Expected valid: {expr!r}"

    def test_is_valid_schedule_false(self):
        for expr in ["every day", "soon", "0 9 * *", "", "none"]:
            assert not is_valid_schedule(expr), f"Expected invalid: {expr!r}"

    def test_describe_schedule_relative(self):
        assert "hour" in describe_schedule("+1h")
        assert "day" in describe_schedule("+1d")

    def test_describe_schedule_named(self):
        assert "every day" in describe_schedule("@daily")

    def test_describe_schedule_cron(self):
        desc = describe_schedule("0 9 * * 1")
        assert "cron" in desc or "0 9" in desc


# ── B. DB CRUD ────────────────────────────────────────────────────────────────

from graph_store import get_graph_store, SQLiteGraphStore


def _make_store(tmp_path):
    return SQLiteGraphStore(tmp_path / "test.db")


class TestAutonomousTaskCRUD:

    def test_create_returns_task_dict(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        task = store.create_autonomous_task(
            task_id=tid, project_id="proj", description="test task",
        )
        assert task['task_id'] == tid
        assert task['description'] == "test task"
        assert task['status'] == 'active'
        assert task['run_count'] == 0

    def test_create_persisted_to_db(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="proj", description="persist test")
        fetched = store.get_autonomous_task(tid)
        assert fetched is not None
        assert fetched['task_id'] == tid

    def test_create_with_schedule(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        nra = time.time() + 3600
        store.create_autonomous_task(
            task_id=tid, project_id="proj", description="scheduled",
            schedule="+1h", next_run_at=nra,
        )
        fetched = store.get_autonomous_task(tid)
        assert fetched['schedule'] == "+1h"
        assert abs(fetched['next_run_at'] - nra) < 1

    def test_create_with_priority(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="proj", description="hi-pri", priority=9)
        assert store.get_autonomous_task(tid)['priority'] == 9

    def test_create_with_max_runs(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="proj", description="limited", max_runs=3)
        assert store.get_autonomous_task(tid)['max_runs'] == 3

    def test_get_nonexistent_returns_none(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.get_autonomous_task("does-not-exist") is None

    def test_list_filters_by_project(self, tmp_path):
        store = _make_store(tmp_path)
        for proj in ["A", "B", "A"]:
            store.create_autonomous_task(
                task_id=str(uuid.uuid4()), project_id=proj, description=f"task for {proj}")
        result = store.list_autonomous_tasks("A")
        assert len(result) == 2
        assert all(t['project_id'] == "A" for t in result)

    def test_list_filters_by_status(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="proj", description="cancel me")
        store.cancel_autonomous_task(tid)
        active = store.list_autonomous_tasks("proj", status='active')
        cancelled = store.list_autonomous_tasks("proj", status='cancelled')
        assert len(active) == 0
        assert len(cancelled) == 1

    def test_cancel_sets_status(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="proj", description="cancel")
        ok = store.cancel_autonomous_task(tid)
        assert ok is True
        assert store.get_autonomous_task(tid)['status'] == 'cancelled'

    def test_cancel_nonexistent_returns_false(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.cancel_autonomous_task("no-such-id") is False

    def test_update_description(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="proj", description="old")
        store.update_autonomous_task(tid, description="new")
        assert store.get_autonomous_task(tid)['description'] == "new"

    def test_update_priority(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="proj", description="x", priority=5)
        store.update_autonomous_task(tid, priority=8)
        assert store.get_autonomous_task(tid)['priority'] == 8

    def test_update_status_to_paused(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="proj", description="x")
        store.update_autonomous_task(tid, status='paused')
        assert store.get_autonomous_task(tid)['status'] == 'paused'

    def test_update_nonexistent_returns_false(self, tmp_path):
        store = _make_store(tmp_path)
        ok = store.update_autonomous_task("bad-id", description="x")
        assert ok is False

    def test_update_ignores_disallowed_fields(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="proj", description="x")
        # run_count is not in _ALLOWED
        ok = store.update_autonomous_task(tid, run_count=999)
        assert ok is False  # no allowed fields → no update

    def test_created_by_persisted(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="proj", description="x", created_by="claude")
        assert store.get_autonomous_task(tid)['created_by'] == "claude"


# ── C. mark_task_run ──────────────────────────────────────────────────────────

class TestMarkTaskRun:

    def test_one_shot_becomes_completed(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="p", description="one-shot")
        store.mark_task_run(tid, run_status='success', note="done")
        t = store.get_autonomous_task(tid)
        assert t['status'] == 'completed'
        assert t['last_run_status'] == 'success'
        assert t['last_run_note'] == "done"
        assert t['run_count'] == 1

    def test_recurring_stays_active_after_run(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        next_run = time.time() + 3600
        store.create_autonomous_task(
            task_id=tid, project_id="p", description="recurring",
            schedule="+1h", next_run_at=time.time(),
        )
        store.mark_task_run(tid, run_status='success', next_run_at=next_run)
        t = store.get_autonomous_task(tid)
        assert t['status'] == 'active'
        assert abs(t['next_run_at'] - next_run) < 1

    def test_max_runs_triggers_completion(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(
            task_id=tid, project_id="p", description="limited",
            schedule="+1h", next_run_at=time.time(), max_runs=2,
        )
        store.mark_task_run(tid, run_status='success', next_run_at=time.time() + 3600)
        assert store.get_autonomous_task(tid)['status'] == 'active'
        store.mark_task_run(tid, run_status='success', next_run_at=time.time() + 7200)
        assert store.get_autonomous_task(tid)['status'] == 'completed'

    def test_run_count_increments(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(
            task_id=tid, project_id="p", description="count",
            schedule="+1h", next_run_at=time.time(),
        )
        for i in range(3):
            store.mark_task_run(tid, run_status='success', next_run_at=time.time() + 3600)
        assert store.get_autonomous_task(tid)['run_count'] == 3

    def test_last_run_at_set(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="p", description="x")
        before = time.time()
        store.mark_task_run(tid, run_status='success')
        after = time.time()
        t = store.get_autonomous_task(tid)
        assert before <= t['last_run_at'] <= after

    def test_failed_run_recorded(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(
            task_id=tid, project_id="p", description="x",
            schedule="+1h", next_run_at=time.time(),
        )
        store.mark_task_run(tid, run_status='failed', note="boom", next_run_at=time.time() + 3600)
        t = store.get_autonomous_task(tid)
        assert t['last_run_status'] == 'failed'
        assert t['last_run_note'] == "boom"

    def test_mark_nonexistent_returns_false(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.mark_task_run("no-such", run_status='success') is False


# ── D. due_only filtering and priority ordering ───────────────────────────────

class TestDueFiltering:

    def test_due_only_excludes_future_tasks(self, tmp_path):
        store = _make_store(tmp_path)
        past_id = str(uuid.uuid4())
        future_id = str(uuid.uuid4())
        store.create_autonomous_task(
            task_id=past_id, project_id="proj", description="past",
            next_run_at=time.time() - 100,
        )
        store.create_autonomous_task(
            task_id=future_id, project_id="proj", description="future",
            next_run_at=time.time() + 10000,
        )
        due = store.list_autonomous_tasks("proj", due_only=True)
        ids = {t['task_id'] for t in due}
        assert past_id in ids
        assert future_id not in ids

    def test_due_before_cutoff(self, tmp_path):
        store = _make_store(tmp_path)
        t1 = str(uuid.uuid4())
        t2 = str(uuid.uuid4())
        now = time.time()
        store.create_autonomous_task(task_id=t1, project_id="p", description="soon", next_run_at=now + 30)
        store.create_autonomous_task(task_id=t2, project_id="p", description="later", next_run_at=now + 7200)
        due = store.list_autonomous_tasks("p", due_only=True, due_before=now + 60)
        ids = {t['task_id'] for t in due}
        assert t1 in ids
        assert t2 not in ids

    def test_priority_ordering_desc(self, tmp_path):
        store = _make_store(tmp_path)
        now = time.time()
        for pri in [3, 7, 5]:
            store.create_autonomous_task(
                task_id=str(uuid.uuid4()), project_id="proj",
                description=f"pri={pri}", priority=pri,
                next_run_at=now - 1,
            )
        tasks = store.list_autonomous_tasks("proj", due_only=True)
        priorities = [t['priority'] for t in tasks]
        assert priorities == sorted(priorities, reverse=True)

    def test_due_only_skips_null_next_run(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="p", description="no schedule")
        due = store.list_autonomous_tasks("p", due_only=True)
        assert all(t['task_id'] != tid for t in due)

    def test_limit_respected(self, tmp_path):
        store = _make_store(tmp_path)
        for _ in range(10):
            store.create_autonomous_task(
                task_id=str(uuid.uuid4()), project_id="proj",
                description="bulk", next_run_at=time.time() - 1,
            )
        result = store.list_autonomous_tasks("proj", due_only=True, limit=3)
        assert len(result) == 3

    def test_paused_tasks_excluded_from_active_list(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="p", description="pause me")
        store.update_autonomous_task(tid, status='paused')
        active = store.list_autonomous_tasks("p", status='active')
        assert all(t['task_id'] != tid for t in active)


# ── E. NativeGraphStore delegation ───────────────────────────────────────────

class TestNativeDelegation:

    def test_native_store_has_all_autonomous_methods(self):
        src = (PLUGIN_ROOT / "mcp_server" / "native_graph_store.py").read_text()
        for method in [
            "create_autonomous_task", "list_autonomous_tasks", "get_autonomous_task",
            "update_autonomous_task", "mark_task_run", "cancel_autonomous_task",
        ]:
            assert method in src, f"Missing method: {method}"

    def test_native_store_delegates_to_sidecar(self):
        src = (PLUGIN_ROOT / "mcp_server" / "native_graph_store.py").read_text()
        assert "_sidecar_store" in src
        assert "ainl_memory.db" in src

    def test_native_store_returns_empty_on_exception(self):
        src = (PLUGIN_ROOT / "mcp_server" / "native_graph_store.py").read_text()
        # All delegation methods must have try/except guards
        assert "except Exception" in src


# ── F. MCP tool schema validation ─────────────────────────────────────────────

class TestMCPToolSchema:

    def _get_tool_snippet(self, tool_name: str, window: int = 800) -> str:
        src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text()
        # Tool() constructors use Python kwarg syntax: name="tool_name"
        idx = src.find(f'name="{tool_name}"')
        assert idx >= 0, f"Tool {tool_name!r} not found in server.py"
        return src[idx: idx + window]

    def test_memory_schedule_task_schema(self):
        snippet = self._get_tool_snippet("memory_schedule_task", 1600)
        assert '"project_id"' in snippet
        assert '"description"' in snippet
        assert '"schedule"' in snippet
        assert '"priority"' in snippet
        assert '"max_runs"' in snippet
        assert '"created_by"' in snippet

    def test_memory_list_scheduled_tasks_schema(self):
        snippet = self._get_tool_snippet("memory_list_scheduled_tasks")
        assert '"project_id"' in snippet
        assert '"status"' in snippet
        assert '"due_only"' in snippet

    def test_memory_complete_task_schema(self):
        snippet = self._get_tool_snippet("memory_complete_task")
        assert '"task_id"' in snippet
        assert '"note"' in snippet
        assert '"reschedule"' in snippet

    def test_memory_cancel_task_schema(self):
        snippet = self._get_tool_snippet("memory_cancel_task")
        assert '"task_id"' in snippet

    def test_memory_update_task_schema(self):
        snippet = self._get_tool_snippet("memory_update_task", 1000)
        assert '"task_id"' in snippet
        assert '"description"' in snippet
        assert '"schedule"' in snippet
        assert '"priority"' in snippet
        assert '"status"' in snippet

    def test_all_five_tools_present(self):
        src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text()
        for tool in [
            "memory_schedule_task", "memory_list_scheduled_tasks",
            "memory_complete_task", "memory_cancel_task", "memory_update_task",
        ]:
            assert f'name="{tool}"' in src, f"Missing tool definition: {tool}"


# ── G. Startup hook injection ─────────────────────────────────────────────────

class TestStartupInjection:

    def test_startup_reads_autonomous_mode_config(self):
        src = (PLUGIN_ROOT / "hooks" / "startup.py").read_text()
        assert "autonomous_mode" in src

    def test_startup_calls_list_autonomous_tasks(self):
        src = (PLUGIN_ROOT / "hooks" / "startup.py").read_text()
        assert "list_autonomous_tasks" in src

    def test_startup_injects_task_block(self):
        src = (PLUGIN_ROOT / "hooks" / "startup.py").read_text()
        assert "AUTONOMOUS TASKS DUE" in src

    def test_startup_calls_memory_complete_task_in_instructions(self):
        src = (PLUGIN_ROOT / "hooks" / "startup.py").read_text()
        assert "memory_complete_task" in src

    def test_startup_uses_due_only_filter(self):
        src = (PLUGIN_ROOT / "hooks" / "startup.py").read_text()
        assert "due_only=True" in src or "due_only" in src

    def test_startup_uses_lookahead_config(self):
        src = (PLUGIN_ROOT / "hooks" / "startup.py").read_text()
        assert "due_tasks_lookahead_minutes" in src

    def test_startup_is_non_fatal(self):
        src = (PLUGIN_ROOT / "hooks" / "startup.py").read_text()
        # Autonomous task injection must be inside a try/except
        idx = src.find("Autonomous task injection")
        snippet = src[max(0, idx - 200): idx + 300]
        assert "except" in snippet or "non-fatal" in snippet

    def test_tool_count_includes_autonomous(self):
        src = (PLUGIN_ROOT / "hooks" / "startup.py").read_text()
        # TOOL_COUNT_MEMORY should be at least 18 now
        import re
        m = re.search(r'TOOL_COUNT_MEMORY\s*=\s*(\d+)', src)
        assert m, "TOOL_COUNT_MEMORY not found"
        assert int(m.group(1)) >= 18


# ── H. Config section validation ─────────────────────────────────────────────

class TestConfigSection:

    def _cfg(self):
        return json.loads((PLUGIN_ROOT / "config.json").read_text())

    def test_autonomous_mode_section_exists(self):
        assert "autonomous_mode" in self._cfg()

    def test_enabled_default_true(self):
        assert self._cfg()["autonomous_mode"]["enabled"] is True

    def test_allow_self_scheduling_present(self):
        assert "allow_self_scheduling" in self._cfg()["autonomous_mode"]

    def test_inject_due_tasks_present(self):
        assert "inject_due_tasks_in_startup" in self._cfg()["autonomous_mode"]

    def test_due_tasks_lookahead_minutes_present(self):
        cfg = self._cfg()["autonomous_mode"]
        assert "due_tasks_lookahead_minutes" in cfg
        assert isinstance(cfg["due_tasks_lookahead_minutes"], (int, float))
        assert cfg["due_tasks_lookahead_minutes"] > 0

    def test_approved_autonomous_actions_is_list(self):
        cfg = self._cfg()["autonomous_mode"]
        assert isinstance(cfg.get("approved_autonomous_actions"), list)
        assert len(cfg["approved_autonomous_actions"]) > 0


# ── I. Server dispatch registration ──────────────────────────────────────────

class TestServerDispatch:

    def test_all_tools_dispatched_in_call_tool(self):
        src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text()
        for tool in [
            "memory_schedule_task", "memory_list_scheduled_tasks",
            "memory_complete_task", "memory_cancel_task", "memory_update_task",
            "memory_list_autonomous_executions",
        ]:
            assert f'name == "{tool}"' in src, f"Missing dispatch for {tool}"

    def test_all_tools_registered_on_server(self):
        src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text()
        for tool in [
            "memory_schedule_task", "memory_list_scheduled_tasks",
            "memory_complete_task", "memory_cancel_task", "memory_update_task",
            "memory_list_autonomous_executions",
        ]:
            assert f"memory_server.{tool} = {tool}" in src, f"Missing registration: {tool}"

    def test_autonomous_scheduler_imported_in_server(self):
        src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text()
        assert "autonomous_scheduler" in src


# ── K. allowed_actions scope lock ─────────────────────────────────────────────

class TestAllowedActions:

    def test_allowed_actions_stored_and_returned(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        actions = ["memory_list_goals", "memory_update_goal"]
        store.create_autonomous_task(
            task_id=tid, project_id="p", description="scoped task",
            allowed_actions=actions,
        )
        t = store.get_autonomous_task(tid)
        # Stored as JSON; SQLite row may return string — parse if needed
        raw = t.get('allowed_actions')
        if isinstance(raw, str):
            raw = json.loads(raw)
        assert raw == actions

    def test_allowed_actions_null_by_default(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="p", description="x")
        t = store.get_autonomous_task(tid)
        assert t.get('allowed_actions') is None

    def test_allowed_actions_updatable(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="p", description="x")
        store.update_autonomous_task(tid, allowed_actions=json.dumps(["memory_search"]))
        t = store.get_autonomous_task(tid)
        raw = t.get('allowed_actions')
        if isinstance(raw, str):
            raw = json.loads(raw)
        assert "memory_search" in raw

    def test_schema_has_allowed_actions_column(self):
        src = (PLUGIN_ROOT / "mcp_server" / "schema.sql").read_text()
        assert "allowed_actions" in src

    def test_server_schedule_task_has_allowed_actions_param(self):
        src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text()
        idx = src.find('name="memory_schedule_task"')
        snippet = src[idx: idx + 1800]
        assert '"allowed_actions"' in snippet

    def test_server_update_task_has_allowed_actions_param(self):
        src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text()
        idx = src.find('name="memory_update_task"')
        snippet = src[idx: idx + 1200]
        assert '"allowed_actions"' in snippet

    def test_claude_md_allowed_actions_enforcement(self):
        src = (PLUGIN_ROOT / "CLAUDE.md").read_text()
        assert "allowed_actions" in src
        assert "whitelist" in src or "hard scope lock" in src or "only" in src.lower()

    def test_startup_surfaces_allowed_actions(self):
        src = (PLUGIN_ROOT / "hooks" / "startup.py").read_text()
        assert "allowed_actions" in src

    def test_backward_compat_migration_in_graph_store(self):
        src = (PLUGIN_ROOT / "mcp_server" / "graph_store.py").read_text()
        assert "ALTER TABLE autonomous_tasks ADD COLUMN allowed_actions" in src

    def test_native_store_passes_allowed_actions(self):
        src = (PLUGIN_ROOT / "mcp_server" / "native_graph_store.py").read_text()
        assert "allowed_actions" in src


# ── L. Execution audit log ────────────────────────────────────────────────────

class TestExecutionAuditLog:

    def test_append_execution_log_creates_file(self, tmp_path):
        from graph_store import append_execution_log
        task = {
            'task_id': 'tid-1', 'project_id': 'proj', 'description': 'test',
            'trigger_type': 'scheduled', 'allowed_actions': None, 'run_count': 0,
        }
        append_execution_log(tmp_path, task, 'success', 'all done', cwd='/tmp', session_id='sid-1')
        log = tmp_path / "logs" / "autonomous_executions.jsonl"
        assert log.exists()
        record = json.loads(log.read_text())
        assert record['task_id'] == 'tid-1'
        assert record['project_id'] == 'proj'
        assert record['run_status'] == 'success'
        assert record['cwd'] == '/tmp'
        assert record['session_id'] == 'sid-1'
        assert 'ts' in record

    def test_append_execution_log_appends(self, tmp_path):
        from graph_store import append_execution_log
        task = {'task_id': 'x', 'project_id': 'p', 'description': 'd',
                'trigger_type': 'scheduled', 'allowed_actions': None, 'run_count': 0}
        for i in range(3):
            append_execution_log(tmp_path, task, 'success', f'run {i}')
        lines = (tmp_path / "logs" / "autonomous_executions.jsonl").read_text().strip().splitlines()
        assert len(lines) == 3

    def test_append_execution_log_never_raises_on_bad_path(self):
        from graph_store import append_execution_log
        # Pass a path that can't be written to — must not raise
        task = {'task_id': 'x', 'project_id': 'p', 'description': 'd',
                'trigger_type': 'scheduled', 'allowed_actions': None, 'run_count': 0}
        append_execution_log(Path("/nonexistent/path"), task, 'success', None)

    def test_complete_task_writes_execution_log_in_server(self):
        src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text()
        assert "append_execution_log" in src
        assert "execution_logged" in src

    def test_audit_tool_in_server(self):
        src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text()
        assert 'name="memory_list_autonomous_executions"' in src
        assert "autonomous_executions.jsonl" in src

    def test_execution_log_includes_allowed_actions(self, tmp_path):
        from graph_store import append_execution_log
        actions = ["memory_list_goals"]
        task = {'task_id': 'x', 'project_id': 'p', 'description': 'd',
                'trigger_type': 'scheduled', 'allowed_actions': actions, 'run_count': 0}
        append_execution_log(tmp_path, task, 'success', None)
        record = json.loads(
            (tmp_path / "logs" / "autonomous_executions.jsonl").read_text()
        )
        assert record['allowed_actions'] == actions

    def test_execution_log_includes_cwd(self, tmp_path):
        from graph_store import append_execution_log
        task = {'task_id': 'x', 'project_id': 'p', 'description': 'd',
                'trigger_type': 'one_shot', 'allowed_actions': None, 'run_count': 0}
        append_execution_log(tmp_path, task, 'failed', 'exploded', cwd='/home/user/myproject')
        record = json.loads(
            (tmp_path / "logs" / "autonomous_executions.jsonl").read_text()
        )
        assert record['cwd'] == '/home/user/myproject'
        assert record['run_status'] == 'failed'


# ── J. Edge cases ─────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_schedule_validation_in_server_source(self):
        src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text()
        assert "is_valid_schedule" in src

    def test_schema_table_in_schema_sql(self):
        src = (PLUGIN_ROOT / "mcp_server" / "schema.sql").read_text()
        assert "autonomous_tasks" in src
        assert "task_id" in src
        assert "priority" in src
        assert "schedule" in src
        assert "next_run_at" in src
        assert "created_by" in src

    def test_schema_has_indexes(self):
        src = (PLUGIN_ROOT / "mcp_server" / "schema.sql").read_text()
        assert "idx_tasks_project" in src
        assert "idx_tasks_priority" in src or "idx_tasks_next_run" in src

    def test_abstract_methods_on_graph_store(self):
        src = (PLUGIN_ROOT / "mcp_server" / "graph_store.py").read_text()
        for method in [
            "create_autonomous_task", "list_autonomous_tasks", "get_autonomous_task",
            "update_autonomous_task", "mark_task_run", "cancel_autonomous_task",
        ]:
            assert f"def {method}" in src, f"Missing abstract method: {method}"

    def test_parse_next_run_always_returns_float(self):
        for expr in ["+1m", "+1h", "+1d", "@daily", "* * * * *"]:
            result = parse_next_run(expr)
            assert isinstance(result, float), f"Expected float for {expr!r}, got {type(result)}"

    def test_parse_next_run_result_is_in_future(self):
        before = time.time()
        for expr in ["+30m", "@hourly", "@daily"]:
            result = parse_next_run(expr, since=before)
            assert result > before, f"Expected future timestamp for {expr!r}"

    def test_is_valid_schedule_never_raises(self):
        # Should never raise, even on garbage input
        for bad in [None, 123, [], {}, "", "   ", "\x00"]:
            try:
                result = is_valid_schedule(str(bad) if bad is not None else "")
                assert isinstance(result, bool)
            except Exception as e:
                pytest.fail(f"is_valid_schedule raised for {bad!r}: {e}")

    def test_db_survives_repeated_schema_init(self, tmp_path):
        """schema.sql runs on every open; must not fail if table already exists."""
        store1 = SQLiteGraphStore(tmp_path / "t.db")
        tid = str(uuid.uuid4())
        store1.create_autonomous_task(task_id=tid, project_id="p", description="x")
        store1.close()
        # Re-open — schema.sql re-runs CREATE IF NOT EXISTS
        store2 = SQLiteGraphStore(tmp_path / "t.db")
        assert store2.get_autonomous_task(tid) is not None
        store2.close()

    def test_list_returns_empty_for_unknown_project(self, tmp_path):
        store = _make_store(tmp_path)
        result = store.list_autonomous_tasks("nonexistent-project")
        assert result == []

    def test_mark_task_run_one_shot_with_note(self, tmp_path):
        store = _make_store(tmp_path)
        tid = str(uuid.uuid4())
        store.create_autonomous_task(task_id=tid, project_id="p", description="x")
        store.mark_task_run(tid, run_status='success', note="all good")
        t = store.get_autonomous_task(tid)
        assert t['last_run_note'] == "all good"
        assert t['status'] == 'completed'
