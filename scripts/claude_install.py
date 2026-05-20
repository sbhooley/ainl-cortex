#!/usr/bin/env python3
"""
One-shot install for Claude Code agents (macOS, Linux, Windows).

Claude should run this after cloning or enabling the plugin — no separate
setup.sh / setup.ps1 required when Python 3.10+ is on PATH.

  python scripts/claude_install.py
  py -3 scripts/claude_install.py          # Windows fallback
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.install_bootstrap import ensure_plugin_installed, is_safe_install_root  # noqa: E402
from mcp_server.platform_paths import is_windows, plugin_root  # noqa: E402


def main() -> int:
    root = plugin_root(ROOT)
    print(f"=== AINL Cortex install (Claude agent) ===")
    print(f"  Plugin: {root}")
    print(f"  Platform: {'windows' if is_windows() else 'unix'}")

    if not is_safe_install_root(root):
        print(
            "ERROR: install from a permanent directory, e.g.\n"
            "  Windows: %USERPROFILE%\\.claude\\plugins\\ainl-cortex\n"
            "  macOS:   ~/.claude/plugins/ainl-cortex",
            file=sys.stderr,
        )
        return 1

    ok, msg = ensure_plugin_installed(root, python_only=True, register_claude=True, force=True)
    if ok:
        print(f"  [ok] {msg}")
        print("")
        print("  Tell the user to restart Claude Code, then run /reload-plugins.")
        return 0

    print(f"  [fail] {msg}", file=sys.stderr)
    if is_windows() and "Python not found" in msg:
        print(
            "  On Windows, install Python from python.org with 'Add to PATH', "
            "or run: winget install Python.Python.3.12",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
