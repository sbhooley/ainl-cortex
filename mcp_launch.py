#!/usr/bin/env python3
"""Cross-platform MCP server launcher (Windows + macOS + Linux)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from mcp_server.platform_paths import plugin_root, pythonpath_for_plugin, venv_python

    root = plugin_root(ROOT)
    os.environ.setdefault("CLAUDE_PLUGIN_ROOT", str(root))
    os.environ["PYTHONPATH"] = pythonpath_for_plugin(root)

    try:
        from mcp_server.hook_launcher_heal import ensure_hook_launchers

        _h_ok, _h_msg = ensure_hook_launchers(root)
        if _h_msg.startswith("repaired:"):
            print(f"ainl-cortex: {_h_msg}", file=sys.stderr)
    except Exception:
        pass

    vpy = venv_python(root)
    if vpy is None:
        from mcp_server.install_bootstrap import ensure_plugin_installed, needs_install

        if needs_install(root):
            ok, install_msg = ensure_plugin_installed(root)
            if not ok:
                print(f"ainl-cortex: auto-install failed: {install_msg}", file=sys.stderr)
                print(
                    "  Manual setup:\n"
                    "    python scripts/claude_install.py\n"
                    "    Windows: powershell -ExecutionPolicy Bypass -File setup.ps1\n"
                    "    macOS/Linux: bash setup.sh",
                    file=sys.stderr,
                )
                return 1
            print(f"ainl-cortex: {install_msg}", file=sys.stderr)
            vpy = venv_python(root)
        if vpy is None:
            print(
                "ainl-cortex: .venv still missing after install attempt.",
                file=sys.stderr,
            )
            return 1

    if Path(sys.executable).resolve() != vpy.resolve():
        os.execv(str(vpy), [str(vpy), "-m", "mcp_server.server"])

    preflight = root / "scripts" / "ensure_runtime_preflight.py"
    if preflight.is_file():
        subprocess.run([str(vpy), str(preflight)], cwd=str(root), check=False)

    from mcp_server.runtime_bootstrap import bootstrap_runtime

    bootstrap_runtime(root, record_mcp_runtime=True)

    import asyncio
    from mcp_server.server import main as server_main

    asyncio.run(server_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
