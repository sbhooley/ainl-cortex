"""Dependency self-heal: ainativelang in the plugin venv."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from .import_compat import plugin_root, venv_python

logger = logging.getLogger(__name__)

_AINL_PYPI_SPEC = "ainativelang[mcp]>=1.8.0,<2.0.0"
_ainl_install_attempted = False


def ainativelang_importable() -> bool:
    try:
        import compiler_v2  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_ainativelang(root: Optional[Path] = None, *, force: bool = False) -> Tuple[bool, str]:
    """
    Idempotent pip install of ainativelang into the plugin venv.

    Returns (success, short_status_message). Never raises.
    """
    global _ainl_install_attempted
    root = root or plugin_root()
    if ainativelang_importable() and not force:
        return True, "ainativelang already importable"

    py = venv_python(root)
    if py is None:
        return False, "no venv python for pip install"

    req = root / "requirements-ainl.txt"
    cmd = [str(py), "-m", "pip", "install", "--upgrade", "--quiet"]
    if req.is_file():
        cmd.extend(["-r", str(req)])
    else:
        cmd.append(_AINL_PYPI_SPEC)

    if _ainl_install_attempted and not force:
        if ainativelang_importable():
            return True, "ainativelang importable after prior install"
        return False, "ainativelang install already attempted this process"

    _ainl_install_attempted = True
    try:
        r = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()[:240]
            logger.warning("ensure_ainativelang pip failed: %s", err)
            return False, f"pip install failed: {err}"
    except subprocess.TimeoutExpired:
        return False, "pip install timed out (>5 min)"
    except Exception as exc:
        return False, f"pip install error: {exc}"

    if ainativelang_importable():
        logger.info("Auto-installed ainativelang into plugin venv")
        return True, "installed ainativelang"
    return False, "pip succeeded but compiler_v2 still not importable"


def reload_ainl_tools_class():
    """Force re-import of ainl_tools after pip install (same process)."""
    for mod in ("ainl_tools", "mcp_server.ainl_tools"):
        sys.modules.pop(mod, None)
    try:
        from . import ainl_tools as at  # noqa: WPS433
        return at
    except ImportError:
        import ainl_tools as at  # noqa: WPS433
        return at


def create_ainl_tools_if_possible(db_path: Path):
    """Return AINLTools instance or None after optional heal."""
    ok, _ = ensure_ainativelang()
    if not ok and not ainativelang_importable():
        return None
    try:
        mod = reload_ainl_tools_class()
        if not getattr(mod, "_HAS_AINL", False):
            return None
        return mod.AINLTools(memory_db_path=db_path)
    except Exception as exc:
        logger.warning("AINLTools init failed: %s", exc)
        return None
