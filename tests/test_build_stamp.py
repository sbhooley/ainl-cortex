"""MCP runtime stamp and stale-PID pruning."""

import json
import os

from mcp_server.build_stamp import prune_stale_mcp_runtime, read_mcp_runtime, write_mcp_runtime_stamp
from mcp_server.mcp_reload import clear_reload_request, reload_nudge_message


def test_prune_stale_mcp_runtime_removes_dead_pid(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    logs = tmp_path / "logs"
    logs.mkdir()
    dead_pid = 99999999
    (logs / "mcp_runtime.json").write_text(
        json.dumps({"git_sha": "abc", "pid": dead_pid, "started_at": 1}),
        encoding="utf-8",
    )
    assert prune_stale_mcp_runtime(tmp_path) is True
    assert not (logs / "mcp_runtime.json").exists()
    assert read_mcp_runtime(tmp_path) is None


def test_reload_nudge_clear_when_disk_matches_fresh_stamp(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    (tmp_path / "logs").mkdir()
    (tmp_path / ".git").mkdir()
    # minimal git repo not required — write_mcp_runtime uses git rev-parse; skip if no git
    sha = write_mcp_runtime_stamp(tmp_path)
    if not sha:
        return
    clear_reload_request(tmp_path)
    assert reload_nudge_message(tmp_path) is None
