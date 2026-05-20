"""
Self-heal hook launchers (Windows run_hook.cmd + hooks.json).

Fixes the legacy ``%~dp0..`` + ``ROOT:~0,-1%`` bug that pointed ROOT at
``.../scripts/.`` and broke SessionStart + PostToolUse hooks.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from .platform_paths import hook_command, is_windows, plugin_root

logger = logging.getLogger(__name__)

# Pre-f739b2d run_hook.cmd used this substring trick (breaks plugin root resolution).
_BROKEN_RUN_HOOK_MARKERS = ("ROOT:~0,-1%", "%ROOT:~0,-1%")

_CANONICAL_RUN_HOOK_CMD = r"""@echo off
setlocal
REM Resolve plugin root (this file lives in scripts\). Do NOT use %~dp0.. + substring — that yields scripts\. on Windows.
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
REM Self-heal: legacy installs left ROOT at scripts\. (hooks could not find .venv or startup.py).
if not exist "%ROOT%\hooks\startup.py" (
  for %%J in ("%~dp0..") do set "ROOT=%%~fJ"
)
if exist "%ROOT%\.venv\Scripts\python.exe" (
  "%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\run_hook.py" %*
  exit /b %ERRORLEVEL%
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\bootstrap_no_python.ps1" "%ROOT%"
if errorlevel 1 exit /b 1
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\run_hook.py" %*
exit /b %ERRORLEVEL%
"""


def _startup_marker(root: Path) -> Path:
    return root / "hooks" / "startup.py"


def run_hook_cmd_needs_repair(root: Path) -> bool:
    """True when Windows run_hook.cmd is missing or has the broken ROOT logic."""
    if not is_windows():
        return False
    path = root / "scripts" / "run_hook.cmd"
    if not path.is_file():
        return True
    text = path.read_text(encoding="utf-8", errors="replace")
    if any(marker in text for marker in _BROKEN_RUN_HOOK_MARKERS):
        return True
    if "for %%I in" not in text and "for %%i in" not in text:
        return True
    if 'not exist "%ROOT%\\hooks\\startup.py"' not in text:
        return True
    return False


def hooks_json_needs_repair(root: Path) -> bool:
    """True when hooks.json does not use platform hook_command() entries."""
    path = root / "hooks" / "hooks.json"
    if not path.is_file():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True

    hooks = data.get("hooks") or {}
    session = hooks.get("SessionStart") or []
    for block in session:
        for h in block.get("hooks") or []:
            cmd = (h.get("command") or "").strip()
            if not cmd:
                continue
            if is_windows():
                if "run_hook.cmd" not in cmd:
                    return True
            elif "run_hook.py" not in cmd:
                return True
    return False


def hook_launchers_healthy(root: Optional[Path] = None) -> Tuple[bool, str]:
    """Report whether hook launchers match this OS (no repair performed)."""
    root = root or plugin_root()
    issues: List[str] = []
    if run_hook_cmd_needs_repair(root):
        issues.append("run_hook.cmd")
    if hooks_json_needs_repair(root):
        issues.append("hooks.json")
    if not issues:
        return True, "ok"
    return False, ", ".join(issues)


def repair_run_hook_cmd(root: Path) -> bool:
    """Write canonical run_hook.cmd. Returns True if file was created or updated."""
    if not is_windows():
        return False
    path = root / "scripts" / "run_hook.cmd"
    text = _CANONICAL_RUN_HOOK_CMD
    if path.is_file() and path.read_text(encoding="utf-8", errors="replace") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\r\n")
    logger.info("repaired %s", path)
    return True


def repair_hooks_json(root: Path) -> bool:
    """Regenerate hooks/hooks.json with platform hook_command(). Returns True if rewritten."""
    if not _startup_marker(root).is_file():
        return False
    try:
        import importlib.util

        mod_path = root / "scripts" / "setup_install.py"
        spec = importlib.util.spec_from_file_location("ainl_setup_install", mod_path)
        if spec is None or spec.loader is None:
            return False
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.write_hooks_json(root)
        return True
    except Exception as exc:
        logger.warning("repair_hooks_json failed: %s", exc)
        return False


def ensure_hook_launchers(root: Optional[Path] = None) -> Tuple[bool, str]:
    """
    Idempotent repair for Windows hook launchers. Never raises.

    Safe on every MCP start, run_hook.py invocation, and install.
  """
    root = root or plugin_root()
    if not _startup_marker(root).is_file():
        return True, "skipped (not ainl-cortex root)"

    repairs: List[str] = []
    try:
        if is_windows() and repair_run_hook_cmd(root):
            repairs.append("run_hook.cmd")
        if hooks_json_needs_repair(root):
            if repair_hooks_json(root):
                repairs.append("hooks.json")
    except OSError as exc:
        return False, f"hook launcher repair failed: {exc}"

    if repairs:
        return True, "repaired: " + ", ".join(repairs)
    return True, "ok"
