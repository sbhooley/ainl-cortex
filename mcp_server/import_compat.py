"""
Import compatibility for package-mode MCP (``python -m mcp_server.server``).

Many modules use bare ``from node_types import …``. Claude Code loads the server as a
package, so those imports fail unless ``node_types`` is registered in ``sys.modules``.
This module heals that automatically at launch, setup, session start, and tool dispatch.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_healed_once = False


def plugin_root() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def expected_node_types_file(root: Optional[Path] = None) -> Path:
    root = root or plugin_root()
    return (root / "mcp_server" / "node_types.py").resolve()


def ensure_sys_path(root: Optional[Path] = None) -> None:
    """Ensure plugin root and mcp_server/ are on sys.path (idempotent)."""
    root = root or plugin_root()
    mcp_dir = root / "mcp_server"
    for p in (str(mcp_dir), str(root)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _node_types_module_matches(mod: object, root: Path) -> bool:
    mod_file = getattr(mod, "__file__", None)
    if not mod_file:
        return False
    try:
        return Path(mod_file).resolve() == expected_node_types_file(root)
    except OSError:
        return False


def _load_node_types_module(root: Path):
    ensure_sys_path(root)
    try:
        from mcp_server import node_types as nt  # noqa: WPS433
        return nt
    except ImportError:
        pass
    try:
        from . import node_types as nt  # noqa: WPS433
        return nt
    except ImportError:
        pass
    import node_types as nt  # noqa: WPS433
    return nt


def ensure_node_types_alias(*, force: bool = False) -> bool:
    """
    Register ``node_types`` in ``sys.modules`` for bare imports.

    Returns True when bare ``import node_types`` should work. Never raises.
    """
    global _healed_once
    root = plugin_root()
    ensure_sys_path(root)

    existing = sys.modules.get("node_types")
    if existing is not None and not force:
        if _node_types_module_matches(existing, root):
            _healed_once = True
            return True
        force = True

    if force and "node_types" in sys.modules:
        del sys.modules["node_types"]

    try:
        nt = _load_node_types_module(root)
    except ImportError as exc:
        logger.debug("ensure_node_types_alias: could not load node_types: %s", exc)
        return False

    sys.modules["node_types"] = nt
    if not _healed_once:
        logger.debug("ensure_node_types_alias: registered sys.modules['node_types']")
    _healed_once = True
    return True


def is_node_types_import_error(exc: BaseException) -> bool:
    if isinstance(exc, ModuleNotFoundError):
        return exc.name == "node_types" or "node_types" in str(exc)
    if isinstance(exc, ImportError):
        msg = str(exc).lower()
        return "node_types" in msg or "no module named 'node_types'" in msg
    return False


def heal_import_error(exc: BaseException) -> bool:
    """If *exc* is a node_types import failure, heal and return True."""
    if not is_node_types_import_error(exc):
        return False
    if ensure_node_types_alias(force=True):
        logger.info("Auto-healed node_types import (was: %s)", exc)
        return True
    return False


def verify_bare_node_types_import() -> bool:
    """Return True if a bare ``from node_types import failure_content_id`` works."""
    if not ensure_node_types_alias():
        return False
    try:
        from node_types import failure_content_id  # noqa: F401
        return callable(failure_content_id)
    except ImportError:
        return False
