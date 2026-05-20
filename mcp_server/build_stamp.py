"""Detect stale MCP processes after git pull (disk HEAD vs running MCP SHA)."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .import_compat import plugin_root


def _logs_dir(root: Path) -> Path:
    d = root / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def current_git_head(root: Optional[Path] = None) -> Optional[str]:
    root = root or plugin_root()
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if r.returncode == 0:
            return (r.stdout or "").strip() or None
    except Exception:
        pass
    return None


def write_install_stamp(root: Optional[Path] = None) -> Optional[str]:
    """Called from setup.sh preflight — records expected code version on disk."""
    root = root or plugin_root()
    sha = current_git_head(root) or "unknown"
    payload = {
        "git_sha": sha,
        "written_at": time.time(),
        "written_by": "install",
    }
    try:
        (_logs_dir(root) / "mcp_install_stamp.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return None
    return sha


def write_mcp_runtime_stamp(root: Optional[Path] = None) -> Optional[str]:
    """Called when MCP server process starts."""
    root = root or plugin_root()
    sha = current_git_head(root) or "unknown"
    payload = {
        "git_sha": sha,
        "pid": os.getpid(),
        "started_at": time.time(),
    }
    try:
        (_logs_dir(root) / "mcp_runtime.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        from .mcp_reload import clear_reload_request
        clear_reload_request(root)
    except OSError:
        return None
    return sha


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def prune_stale_mcp_runtime(root: Optional[Path] = None) -> bool:
    """
    Remove ``mcp_runtime.json`` when its recorded PID is no longer running.

    Prevents perpetual stale-MCP banners after restarts when the new MCP process
  failed to refresh the stamp (or preflight left a dead PID on disk).
    """
    root = root or plugin_root()
    path = _logs_dir(root) / "mcp_runtime.json"
    if not path.is_file():
        return False
    try:
        runtime = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return True
    pid = runtime.get("pid")
    if pid is not None and _pid_alive(int(pid)):
        return False
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return True


def read_mcp_runtime(root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    root = root or plugin_root()
    prune_stale_mcp_runtime(root)
    path = _logs_dir(root) / "mcp_runtime.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def stale_mcp_message(root: Optional[Path] = None) -> Optional[str]:
    from .mcp_reload import reload_nudge_message
    return reload_nudge_message(root)


def check_stale_mcp(root: Optional[Path] = None) -> Tuple[bool, str]:
    from .mcp_reload import check_reload_needed
    return check_reload_needed(root)
