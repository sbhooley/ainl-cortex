"""Request MCP reload after plugin updates (Claude Code ``/reload-plugins``)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .build_stamp import current_git_head, read_mcp_runtime
from .import_compat import plugin_root


def _logs_dir(root: Path) -> Path:
    d = root / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def request_mcp_reload(root: Optional[Path] = None, *, reason: str = "plugin_updated") -> None:
    """Record that MCP should reload to pick up on-disk plugin changes."""
    root = root or plugin_root()
    payload = {
        "requested_at": time.time(),
        "reason": reason,
        "disk_git_sha": current_git_head(root),
    }
    try:
        (_logs_dir(root) / "mcp_reload_requested.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def read_reload_request(root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    root = root or plugin_root()
    path = _logs_dir(root) / "mcp_reload_requested.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def clear_reload_request(root: Optional[Path] = None) -> None:
    root = root or plugin_root()
    try:
        (_logs_dir(root) / "mcp_reload_requested.json").unlink(missing_ok=True)
    except OSError:
        pass


def _runtime_sha_stale(root: Path) -> Optional[str]:
    from .build_stamp import prune_stale_mcp_runtime

    prune_stale_mcp_runtime(root)
    disk_sha = current_git_head(root)
    if not disk_sha:
        return None
    runtime = read_mcp_runtime(root)
    if not runtime:
        return None
    run_sha = runtime.get("git_sha")
    if not run_sha or run_sha == disk_sha:
        return None
    return f"Disk build {disk_sha[:8]} vs running MCP {str(run_sha)[:8]}."


def reload_nudge_message(root: Optional[Path] = None) -> Optional[str]:
    """
    User-facing nudge when disk code != running MCP or reload was requested.

    Prefer ``/reload-plugins`` (Claude Code) before a full IDE restart.
    """
    root = root or plugin_root()
    stale_detail = _runtime_sha_stale(root)
    req = read_reload_request(root)
    if not stale_detail and not req:
        return None
    lines = [
        "AINL Cortex plugin code on disk is newer than the running MCP server.",
    ]
    if stale_detail:
        lines.append(stale_detail)
    lines.extend([
        "First try: type **/reload-plugins** in Claude Code (reloads MCP without a full quit).",
        "If tools still look stale or errors persist, fully quit and restart Claude Code once.",
    ])
    if req and req.get("reason"):
        lines.append(f"(Reload requested: {req.get('reason')})")
    return "\n".join(lines)


def check_reload_needed(root: Optional[Path] = None) -> Tuple[bool, str]:
    msg = reload_nudge_message(root)
    if msg:
        return True, msg
    return False, ""
