"""Hook launcher self-heal (Windows run_hook.cmd + hooks.json)."""

import json
import sys
from pathlib import Path

import pytest

from mcp_server.hook_launcher_heal import (
    ensure_hook_launchers,
    hook_launchers_healthy,
    repair_run_hook_cmd,
    run_hook_cmd_needs_repair,
)


def test_run_hook_cmd_detects_broken_substring_pattern(tmp_path):
    cmd = tmp_path / "scripts" / "run_hook.cmd"
    cmd.parent.mkdir(parents=True)
    cmd.write_text(
        '@echo off\nset "ROOT=%~dp0.."\nset "ROOT=%ROOT:~0,-1%"\n',
        encoding="utf-8",
    )
    if sys.platform == "win32":
        assert run_hook_cmd_needs_repair(tmp_path) is True
    else:
        assert run_hook_cmd_needs_repair(tmp_path) is False


def test_repair_run_hook_cmd_writes_canonical(tmp_path, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows-only repair")
    monkeypatch.setattr("mcp_server.hook_launcher_heal.is_windows", lambda: True)
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "startup.py").write_text("", encoding="utf-8")
    broken = tmp_path / "scripts" / "run_hook.cmd"
    broken.parent.mkdir(parents=True)
    broken.write_text('set "ROOT=%ROOT:~0,-1%"', encoding="utf-8")
    assert repair_run_hook_cmd(tmp_path) is True
    text = broken.read_text(encoding="utf-8")
    assert "for %%I in" in text
    assert "ROOT:~0,-1%" not in text
    assert 'not exist "%ROOT%\\hooks\\startup.py"' in text


def test_ensure_hook_launchers_idempotent(tmp_path, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows-only")
    monkeypatch.setattr("mcp_server.hook_launcher_heal.is_windows", lambda: True)
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "startup.py").write_text("", encoding="utf-8")
    repair_run_hook_cmd(tmp_path)
    ok, msg = ensure_hook_launchers(tmp_path)
    assert ok is True
    healthy, _ = hook_launchers_healthy(tmp_path)
    assert healthy is True or "hooks.json" in msg
