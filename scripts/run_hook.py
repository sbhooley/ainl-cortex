#!/usr/bin/env python3
"""Cross-platform hook runner (invoked from hooks.json)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: run_hook.py <hook_module>", file=sys.stderr)
        return 2

    hook_name = sys.argv[1].removesuffix(".py")
    hook_file = ROOT / "hooks" / f"{hook_name}.py"
    if not hook_file.is_file():
        print(f"hook not found: {hook_file}", file=sys.stderr)
        return 1

    from mcp_server.platform_paths import plugin_root, pythonpath_for_plugin, venv_python

    root = plugin_root(ROOT)
    os.environ["CLAUDE_PLUGIN_ROOT"] = str(root)
    os.environ["PYTHONPATH"] = pythonpath_for_plugin(root)

    vpy = venv_python(root)
    if vpy is None:
        print("ainl-cortex: .venv missing — run setup.sh or setup.ps1", file=sys.stderr)
        return 1

    if Path(sys.executable).resolve() != vpy.resolve():
        os.execv(
            str(vpy),
            [str(vpy), str(hook_file), *sys.argv[2:]],
        )

    # Already on venv interpreter — run hook in-process.
    sys.path.insert(0, str(root / "hooks"))
    import runpy

    runpy.run_path(str(hook_file), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
