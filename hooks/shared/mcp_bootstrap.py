"""
Bootstrap MCP imports for hook subprocesses.

Hooks add ``mcp_server/`` to ``sys.path`` and bare-import modules (``from config import …``).
After the relative-import codemod, those modules must load via ``mcp_server.<name>`` shims
(see ``mcp_server.import_compat``). Call ``ensure_hook_mcp_imports()`` before any bare
``mcp_server`` import in a hook entrypoint.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BOOTSTRAPPED = False


def plugin_root() -> Path:
    env = __import__("os").environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent.parent


def ensure_hook_mcp_imports(*, force: bool = False) -> bool:
    """Register bare-name shims for ``mcp_server.*`` modules. Idempotent."""
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED and not force:
        return True

    root = plugin_root()
    hooks = root / "hooks"
    mcp = root / "mcp_server"
    for p in (str(root), str(mcp), str(hooks)):
        if p not in sys.path:
            sys.path.insert(0, p)

    ok = False
    try:
        from mcp_server.import_compat import ensure_mcp_module_shims, hook_recall_imports_ok

        ok = hook_recall_imports_ok(force=force) and ensure_mcp_module_shims(force=force)
    except Exception:
        try:
            from import_compat import ensure_mcp_module_shims, hook_recall_imports_ok

            ok = hook_recall_imports_ok(force=force) and ensure_mcp_module_shims(force=force)
        except Exception:
            ok = False

    _BOOTSTRAPPED = ok
    return ok
