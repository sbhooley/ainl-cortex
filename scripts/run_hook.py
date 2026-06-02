#!/usr/bin/env python3
"""Cross-platform hook runner (invoked from hooks.json)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _bootstrap_hook_imports(root: Path) -> None:
    """Register mcp_server bare-import shims before any hook module loads."""
    hooks = root / "hooks"
    for p in (str(root), str(root / "mcp_server"), str(hooks)):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        from shared.mcp_bootstrap import ensure_hook_mcp_imports

        ensure_hook_mcp_imports()
        return
    except Exception:
        pass
    try:
        from mcp_server.import_compat import ensure_mcp_module_shims, ensure_sys_path

        ensure_sys_path(root)
        ensure_mcp_module_shims()
    except Exception:
        pass


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
                print(
                    f"ainl-cortex: auto-install failed: {install_msg}",
                    file=sys.stderr,
                )
                return 1
            vpy = venv_python(root)
        if vpy is None:
            print(
                "ainl-cortex: .venv missing — run: python scripts/claude_install.py",
                file=sys.stderr,
            )
            return 1

    if Path(sys.executable).resolve() != vpy.resolve():
        os.execv(
            str(vpy),
            [str(vpy), str(__file__), hook_name, *sys.argv[2:]],
        )

    # Already on venv interpreter — run hook in-process.
    _bootstrap_hook_imports(root)
    sys.path.insert(0, str(root / "hooks"))
    import runpy

    runpy.run_path(str(hook_file), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
