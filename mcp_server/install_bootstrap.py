"""
Zero-touch install: venv, deps, hooks, marketplace, settings.

Called from MCP launch, hook runner, and ``scripts/claude_install.py`` so users
(and Claude agents) do not need separate setup.sh / setup.ps1 steps when Python
is already on PATH.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

from . import deps_compat
from .platform_paths import (
    find_system_python,
    is_windows,
    plugin_root,
    read_install_manifest,
    venv_python,
)  # is_windows used for setup.ps1 version gate

logger = logging.getLogger(__name__)

_INSTALL_ATTEMPTED: dict[str, float] = {}
_INSTALL_COOLDOWN_SEC = 120.0


SETUP_PS1_VERSION_MARKER = "SETUP_SCRIPT_VERSION=2"


def setup_ps1_is_current(root: Optional[Path] = None) -> bool:
    """True when setup.ps1 includes the PS 5.1-safe version marker."""
    root = root or plugin_root()
    path = root / "setup.ps1"
    if not path.is_file():
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:1200]
    except OSError:
        return False
    return SETUP_PS1_VERSION_MARKER in head


def setup_ps1_stale_message(root: Optional[Path] = None) -> str:
    root = root or plugin_root()
    return (
        f"Plugin at {root} has an outdated setup.ps1 (pre-{SETUP_PS1_VERSION_MARKER}). "
        "Run: git pull  then  setup.cmd -PythonOnly  "
        "(or: powershell -ExecutionPolicy Bypass -File setup.ps1 -PythonOnly). "
        "Do not use: & setup.ps1 -Yes"
    )


def is_safe_install_root(root: Path) -> bool:
    """Skip auto-install for disposable CI / verify temp checkouts."""
    try:
        resolved = root.resolve()
    except OSError:
        return False
    s = str(resolved).replace("\\", "/").lower()
    unsafe = (
        "ainl-cortex-fresh",
        "/private/tmp/ainl-cortex",
        "/tmp/ainl-cortex",
        "/temp/ainl-cortex",
        "\\temp\\ainl-cortex",
    )
    if any(m in s for m in unsafe):
        return False
    return (resolved / "hooks" / "startup.py").is_file()


def needs_install(root: Optional[Path] = None) -> bool:
    root = root or plugin_root()
    if venv_python(root) is None:
        return True
    if not (root / "hooks" / "hooks.json").is_file():
        return True
    manifest = read_install_manifest(root)
    if manifest is None:
        return True
    if not deps_compat.ainativelang_importable():
        ok, _ = deps_compat.ensure_ainativelang(root)
        if ok and deps_compat.ainativelang_importable():
            return False
        return True
    return False


def _run_setup_install(
    root: Path,
    *,
    python_only: bool = True,
    register_claude: bool = False,
) -> Tuple[bool, str]:
    py = venv_python(root) or find_system_python()
    if py is None:
        from .python_bootstrap import ensure_python_for_install

        py_ok, py_msg = ensure_python_for_install(root)
        if not py_ok:
            return False, py_msg
        py = venv_python(root) or find_system_python()
        if py is None:
            return False, f"Python bootstrap finished but no interpreter found ({py_msg})"

    script = root / "scripts" / "setup_install.py"
    if not script.is_file():
        return False, f"missing {script}"

    cmd = [str(py), str(script), "--plugin-dir", str(root)]
    if python_only:
        cmd.append("--python-only")
    if register_claude:
        cmd.append("--register-claude")

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "setup_install.py timed out (>10 min)"
    except OSError as exc:
        return False, f"setup_install failed: {exc}"

    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        tail = out.strip()[-500:]
        return False, f"setup_install exit {proc.returncode}: {tail}"

    if venv_python(root) is None:
        return False, "setup finished but .venv python still missing"

    try:
        from .hook_launcher_heal import ensure_hook_launchers

        ensure_hook_launchers(root)
    except Exception:
        pass

    return True, "venv and dependencies installed"


def register_claude_integration(root: Path) -> Tuple[bool, str]:
    if not is_safe_install_root(root):
        return True, "skipped settings (non-persistent plugin path)"

    try:
        from scripts.configure_marketplace import ensure_local_marketplace
        from scripts.register_claude_settings import register
        from scripts.sync_installed_plugins import sync_installed_plugins

        mp = ensure_local_marketplace(root)
        settings = Path.home() / ".claude" / "settings.json"
        register(settings, mp)
        sync_installed_plugins(root)
        return True, f"registered in {settings}"
    except Exception as exc:
        logger.warning("register_claude_integration failed: %s", exc)
        return False, str(exc)


def ensure_plugin_installed(
    root: Optional[Path] = None,
    *,
    python_only: bool = True,
    register_claude: bool = True,
    force: bool = False,
) -> Tuple[bool, str]:
    """
    Idempotent full install. Safe to call from MCP launch and hooks.

    Returns (success, short_message).
    """
    root = root or plugin_root()
    root = canonical_plugin_root(root)

    if is_windows() and not setup_ps1_is_current(root):
        return False, setup_ps1_stale_message(root)

    if not is_safe_install_root(root):
        return False, (
            f"refusing auto-install from ephemeral path: {root}. "
            "Clone to ~/.claude/plugins/ainl-cortex and run setup, or ask Claude to install from GitHub."
        )

    try:
        from .hook_launcher_heal import ensure_hook_launchers

        _hr_ok, _hr_msg = ensure_hook_launchers(root)
        if _hr_msg.startswith("repaired:"):
            logger.info("hook launcher self-heal: %s", _hr_msg)
    except Exception as exc:
        logger.debug("ensure_hook_launchers: %s", exc)

    if not force and not needs_install(root):
        return True, "already installed"

    key = str(root.resolve())
    now = time.time()
    last = _INSTALL_ATTEMPTED.get(key)
    if not force and last is not None and (now - last) < _INSTALL_COOLDOWN_SEC:
        if venv_python(root) is not None:
            return True, "install recently completed"
        return False, "install failed recently; fix Python/deps and retry"

    _INSTALL_ATTEMPTED[key] = now

    ok, msg = _run_setup_install(
        root, python_only=python_only, register_claude=register_claude
    )
    if not ok:
        return False, msg

    return True, (
        f"{msg}. Restart Claude Code once, then run /reload-plugins if tools are missing."
    )


def ensure_plugin_installed_or_exit(root: Optional[Path] = None) -> Path:
    """Install if needed; return plugin root. Prints to stderr and raises SystemExit on failure."""
    root = root or plugin_root()
    if not needs_install(root):
        return root
    ok, msg = ensure_plugin_installed(root)
    if ok:
        print(f"ainl-cortex: auto-install: {msg}", file=sys.stderr)
        return root
    print(f"ainl-cortex: auto-install failed: {msg}", file=sys.stderr)
    raise SystemExit(1)
