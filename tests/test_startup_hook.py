"""
End-to-end integration tests for hooks/startup.py main().

Previously main() was only tested through source-code inspection.  A startup
regression (bad import, config read, DB init, etc.) would be invisible until
users reported broken session starts.

These tests call main() directly (with stdout captured) and verify the output
contract Claude Code depends on.  All subsystem calls inside main() are already
wrapped in try/except, so non-critical failures are expected and acceptable —
what we're guarding is the outer contract: valid JSON, correct keys, exit 0.

Sections:
  A. Output contract — JSON structure, required keys, exit code
  B. Non-fatal guarantee — bad cwd, missing config, unavailable subsystems
  C. Stale scope-lock clearance during main()
  D. _clear_stale_scope_lock unit tests
"""

import json
import sys
import time
import uuid
from io import StringIO
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
sys.path.insert(0, str(PLUGIN_ROOT))


def _run_main(monkeypatch, plugin_root_override=None, cwd_override=None):
    """
    Run startup.main() with stdout captured. Returns (exit_code, parsed_dict).

    stdout is captured via monkeypatch so the test framework doesn't see it.
    SystemExit is caught; its code is returned alongside the parsed JSON.
    """
    import startup

    if cwd_override is not None:
        monkeypatch.setattr(startup, "_hook_cwd", lambda: Path(cwd_override))
    else:
        monkeypatch.setattr(startup, "_hook_cwd", lambda: PLUGIN_ROOT)

    if plugin_root_override is not None:
        monkeypatch.setattr(startup, "_plugin_root", lambda: Path(plugin_root_override))

    captured = StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    with pytest.raises(SystemExit) as exc:
        startup.main()

    raw = captured.getvalue().strip()
    # Grab only the first complete JSON object (main() prints one line)
    first_line = raw.splitlines()[0] if raw else "{}"
    return exc.value.code, json.loads(first_line)


# ── A. Output contract ────────────────────────────────────────────────────────

class TestStartupOutputContract:

    def test_exit_code_is_zero(self, monkeypatch):
        code, _ = _run_main(monkeypatch)
        assert code == 0

    def test_output_is_valid_json(self, monkeypatch):
        _, data = _run_main(monkeypatch)
        assert isinstance(data, dict)

    def test_continue_is_true(self, monkeypatch):
        _, data = _run_main(monkeypatch)
        assert data.get("continue") is True

    def test_required_keys_present(self, monkeypatch):
        _, data = _run_main(monkeypatch)
        assert "continue" in data
        assert "suppressOutput" in data
        assert "systemMessage" in data
        assert "hookSpecificOutput" in data

    def test_hook_event_name_is_session_start(self, monkeypatch):
        _, data = _run_main(monkeypatch)
        assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"

    def test_system_message_is_nonempty_string(self, monkeypatch):
        _, data = _run_main(monkeypatch)
        msg = data["systemMessage"]
        assert isinstance(msg, str) and len(msg) > 0

    def test_additional_context_mentions_sqlite(self, monkeypatch):
        _, data = _run_main(monkeypatch)
        ctx = data["hookSpecificOutput"].get("additionalContext", "")
        assert "SQLite" in ctx or "db" in ctx.lower()


# ── B. Non-fatal guarantee ────────────────────────────────────────────────────

class TestStartupNonFatal:

    def test_nonexistent_cwd_still_exits_zero(self, monkeypatch):
        """main() must not crash even when cwd doesn't exist."""
        code, data = _run_main(monkeypatch, cwd_override="/nonexistent/path/xyz")
        assert code == 0
        assert data.get("continue") is True

    def test_nonexistent_cwd_produces_valid_json(self, monkeypatch):
        _, data = _run_main(monkeypatch, cwd_override="/nonexistent/path/xyz")
        assert isinstance(data, dict)
        assert "systemMessage" in data

    def test_empty_plugin_root_still_exits_zero(self, monkeypatch, tmp_path):
        """Empty plugin root (no config.json, no .venv) must not crash."""
        code, data = _run_main(monkeypatch, plugin_root_override=tmp_path)
        assert code == 0
        assert data.get("continue") is True

    def test_missing_config_json_still_exits_zero(self, monkeypatch, tmp_path):
        """Plugin root without config.json should degrade gracefully."""
        (tmp_path / "logs").mkdir()
        code, _ = _run_main(monkeypatch, plugin_root_override=tmp_path)
        assert code == 0


# ── C. Stale scope-lock clearance ────────────────────────────────────────────

class TestStartupScopeLockClearance:

    def test_main_clears_stale_active_task_json(self, monkeypatch, tmp_path):
        """A stale active_task.json from a crashed session must be removed at startup."""
        (tmp_path / "logs").mkdir()
        sidecar = tmp_path / "logs" / "active_task.json"
        sidecar.write_text(json.dumps({
            "task_id": "orphaned-" + uuid.uuid4().hex[:8],
            "project_id": "proj",
            "allowed_actions": ["memory_list_goals"],
            "started_at": time.time() - 7200,
        }))

        _run_main(monkeypatch, plugin_root_override=tmp_path)

        assert not sidecar.exists(), (
            "active_task.json should be cleared at session start to prevent permanent scope lock"
        )

    def test_main_noop_when_no_sidecar(self, monkeypatch, tmp_path):
        """startup must not crash when active_task.json is absent."""
        (tmp_path / "logs").mkdir()
        code, _ = _run_main(monkeypatch, plugin_root_override=tmp_path)
        assert code == 0

    def test_main_clears_recent_sidecar_too(self, monkeypatch, tmp_path):
        """Even a recent sidecar should be cleared — new session = old session gone."""
        (tmp_path / "logs").mkdir()
        sidecar = tmp_path / "logs" / "active_task.json"
        sidecar.write_text(json.dumps({
            "task_id": "recent", "project_id": "p",
            "allowed_actions": None, "started_at": time.time() - 10,
        }))
        _run_main(monkeypatch, plugin_root_override=tmp_path)
        assert not sidecar.exists()


# ── D. _clear_stale_scope_lock unit tests ────────────────────────────────────

class TestClearStaleScopeLock:

    def test_removes_existing_sidecar(self, tmp_path):
        from startup import _clear_stale_scope_lock
        (tmp_path / "logs").mkdir()
        sidecar = tmp_path / "logs" / "active_task.json"
        sidecar.write_text('{"task_id": "x"}')
        _clear_stale_scope_lock(tmp_path)
        assert not sidecar.exists()

    def test_noop_when_file_absent(self, tmp_path):
        from startup import _clear_stale_scope_lock
        _clear_stale_scope_lock(tmp_path)  # must not raise

    def test_noop_when_logs_dir_absent(self, tmp_path):
        from startup import _clear_stale_scope_lock
        _clear_stale_scope_lock(tmp_path / "no_such_dir")  # must not raise


# ── E. current_project_id.txt sidecar ────────────────────────────────────────

class TestStartupProjectIdSidecar:

    def test_main_writes_current_project_id_file(self, monkeypatch, tmp_path):
        """startup.main() must write inbox/current_project_id.txt for PreCompact."""
        (tmp_path / "logs").mkdir()
        _run_main(monkeypatch, plugin_root_override=tmp_path)
        sidecar = tmp_path / "inbox" / "current_project_id.txt"
        assert sidecar.exists(), "inbox/current_project_id.txt not written by startup"

    def test_current_project_id_is_nonempty_string(self, monkeypatch, tmp_path):
        (tmp_path / "logs").mkdir()
        _run_main(monkeypatch, plugin_root_override=tmp_path)
        pid = (tmp_path / "inbox" / "current_project_id.txt").read_text().strip()
        assert isinstance(pid, str) and len(pid) > 0

    def test_current_project_id_sidecar_survives_missing_config(self, monkeypatch, tmp_path):
        """Even without config.json the sidecar is written (graceful degradation)."""
        (tmp_path / "logs").mkdir()
        code, _ = _run_main(monkeypatch, plugin_root_override=tmp_path)
        assert code == 0
        assert (tmp_path / "inbox" / "current_project_id.txt").exists()
