"""
Import compatibility for package-mode MCP (``python -m mcp_server.server``).

Primary fix: all mcp_server modules use relative imports (see scripts/codemod_relative_imports.py).
This module keeps sys.path normalization and a minimal legacy shim set for package-root-only
launches and verification smoke tests.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

_healed_once = False

# Minimal legacy shims (full list removed after relative-import codemod).
MCP_BARE_MODULES: Sequence[str] = (
    "node_types",
    "graph_store",
    "retrieval",
    "similarity",
    "native_graph_store",
)


def plugin_root() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def venv_python(root: Optional[Path] = None) -> Optional[Path]:
    root = root or plugin_root()
    bindir = root / ".venv" / "bin"
    for name in ("python", "python3", "python3.14", "python3.13", "python3.12", "python3.11"):
        p = bindir / name
        if p.is_file() and os.access(p, os.X_OK):
            return p
    return None


def expected_module_file(root: Path, bare_name: str) -> Path:
    return (root / "mcp_server" / f"{bare_name}.py").resolve()


def ensure_sys_path(root: Optional[Path] = None) -> None:
    root = root or plugin_root()
    mcp_dir = root / "mcp_server"
    for p in (str(mcp_dir), str(root)):
        if p not in sys.path:
            sys.path.insert(0, p)


def ensure_hooks_path(root: Optional[Path] = None) -> None:
    root = root or plugin_root()
    hooks = root / "hooks"
    if hooks.is_dir() and str(hooks) not in sys.path:
        sys.path.insert(0, str(hooks))


def _module_file_matches(mod: object, expected: Path) -> bool:
    mod_file = getattr(mod, "__file__", None)
    if not mod_file:
        return False
    try:
        return Path(mod_file).resolve() == expected
    except OSError:
        return False


def _load_mcp_bare_module(bare_name: str, root: Path):
    ensure_sys_path(root)
    return importlib.import_module(f"mcp_server.{bare_name}")


def _register_bare_module(bare_name: str, root: Path, *, force: bool = False) -> bool:
    expected = expected_module_file(root, bare_name)
    if not expected.is_file():
        return False
    existing = sys.modules.get(bare_name)
    if existing is not None and not force:
        if _module_file_matches(existing, expected):
            return True
        force = True
    if force and bare_name in sys.modules:
        del sys.modules[bare_name]
    try:
        mod = _load_mcp_bare_module(bare_name, root)
    except ImportError as exc:
        logger.debug("register %s failed: %s", bare_name, exc)
        return False
    sys.modules[bare_name] = mod
    return True


def ensure_mcp_module_shims(*, force: bool = False) -> bool:
    global _healed_once
    root = plugin_root()
    ensure_sys_path(root)
    ensure_hooks_path(root)
    ok = all(_register_bare_module(name, root, force=force) for name in MCP_BARE_MODULES)
    if ok:
        _healed_once = True
    return ok


def ensure_node_types_alias(*, force: bool = False) -> bool:
    return _register_bare_module("node_types", plugin_root(), force=force)


def is_mcp_import_error(exc: BaseException) -> bool:
    names = list(MCP_BARE_MODULES) + ["shared", "compression", "compiler_v2", "mcp_server"]
    if isinstance(exc, ModuleNotFoundError):
        n = exc.name or ""
        return any(n == x or n.startswith(x + ".") for x in names)
    if isinstance(exc, ImportError):
        msg = str(exc).lower()
        return any(x in msg for x in names) or "no module named" in msg
    return False


def is_node_types_import_error(exc: BaseException) -> bool:
    return is_mcp_import_error(exc) and "node_types" in str(exc).lower()


def heal_import_error(exc: BaseException) -> bool:
    if not is_mcp_import_error(exc):
        return False
    if ensure_mcp_module_shims(force=True):
        logger.info("Auto-healed MCP import (was: %s)", exc)
        return True
    return False


def verify_bare_node_types_import() -> bool:
    if not ensure_node_types_alias():
        return False
    try:
        from node_types import failure_content_id  # noqa: F401
        return callable(failure_content_id)
    except ImportError:
        return False


def verify_bare_graph_store_import() -> bool:
    if not _register_bare_module("graph_store", plugin_root()):
        return False
    try:
        from graph_store import get_graph_store  # noqa: F401
        return callable(get_graph_store)
    except ImportError:
        return False


def verify_bare_retrieval_import() -> bool:
    if not _register_bare_module("retrieval", plugin_root()):
        return False
    try:
        from retrieval import MemoryRetrieval  # noqa: F401
        return MemoryRetrieval is not None
    except ImportError:
        return False
