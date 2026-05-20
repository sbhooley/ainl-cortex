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

    vpy = venv_python(root)
    if vpy is None:
        print(
            "ainl-cortex: .venv not found. Run setup:\n"
            "  macOS/Linux: bash setup.sh\n"
            "  Windows:     powershell -ExecutionPolicy Bypass -File setup.ps1",
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
