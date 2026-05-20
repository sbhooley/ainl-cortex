"""Platform-appropriate MCP entry in .claude-plugin/plugin.json (install time)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .platform_paths import is_windows, plugin_root


def configure_mcp_launcher(root: Path | None = None) -> None:
    """
    Windows: ``cmd /c mcp_launch.cmd`` (works with no system Python on PATH).
    Other: ``python mcp_launch.py``.
    """
    root = root or plugin_root()
    path = root / ".claude-plugin" / "plugin.json"
    if not path.is_file():
        return
    data: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers") or {}
    entry = servers.get("ainl-cortex")
    if not isinstance(entry, dict):
        return

    if is_windows():
        entry["command"] = "cmd"
        entry["args"] = ["/c", "${CLAUDE_PLUGIN_ROOT}/mcp_launch.cmd"]
    else:
        entry["command"] = "python3"
        entry["args"] = ["${CLAUDE_PLUGIN_ROOT}/mcp_launch.py"]
    entry["cwd"] = "${CLAUDE_PLUGIN_ROOT}"
    servers["ainl-cortex"] = entry
    data["mcpServers"] = servers
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
