"""Operator-visible preflight: failures we cannot auto-fix, surfaced clearly in SessionStart."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from .import_compat import plugin_root, venv_python


def hook_mcp_imports_ok(root: Optional[Path] = None) -> Tuple[bool, str]:
    """Verify hook subprocesses can bare-import mcp_server modules (memory recall)."""
    root = root or plugin_root()
    try:
        import sys

        hooks = root / "hooks"
        for p in (str(root), str(root / "mcp_server"), str(hooks)):
            if p not in sys.path:
                sys.path.insert(0, p)
        from shared.mcp_bootstrap import ensure_hook_mcp_imports

        if not ensure_hook_mcp_imports(force=True):
            return False, "MCP import shims incomplete — run /reload-plugins"
        from config import get_config

        get_config().get_memory_block()
        return True, "hook recall imports ok"
    except Exception as exc:
        return False, f"hook recall imports broken: {exc}"


def _settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def plugin_enabled_in_claude() -> Tuple[bool, str]:
    path = _settings_path()
    if not path.is_file():
        return False, f"{path} missing — run bash setup.sh"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        enabled = data.get("enabledPlugins", {})
        if enabled.get("ainl-cortex@ainl-local") is True:
            return True, "plugin enabled in settings.json"
        return False, 'enable "ainl-cortex@ainl-local" in ~/.claude/settings.json (or run setup.sh)'
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"cannot read settings.json: {exc}"


def python_version_ok() -> Tuple[bool, str]:
    if sys.version_info < (3, 10):
        return False, f"Python {sys.version_info.major}.{sys.version_info.minor} — need 3.10+"
    return True, f"Python {sys.version_info.major}.{sys.version_info.minor}"


def venv_present(root: Optional[Path] = None) -> Tuple[bool, str]:
    root = root or plugin_root()
    py = venv_python(root)
    if py:
        return True, f"venv: {py.name}"
    if (root / ".venv").is_dir():
        return False, ".venv exists but no python binary — re-run bash setup.sh"
    return False, "no .venv — run bash setup.sh from the plugin directory"


def system_python_available() -> Tuple[bool, str]:
    if sys.platform == "win32":
        for name in ("python", "py"):
            if shutil.which(name):
                return True, f"{name} on PATH"
        return False, "python not found on PATH — install Python 3.10+ from python.org"
    if shutil.which("python3"):
        return True, "python3 on PATH"
    return False, "python3 not found on PATH — install Python 3.10+"


def collect_operator_issues(root: Optional[Path] = None) -> List[str]:
    """Non-empty list = actionable operator steps (not auto-healable)."""
    root = root or plugin_root()
    issues: List[str] = []
    ok, msg = plugin_enabled_in_claude()
    if not ok:
        issues.append(f"Plugin registration: {msg}")
    ok, msg = venv_present(root)
    if not ok:
        issues.append(f"Venv: {msg}")
    ok, msg = system_python_available()
    if not ok:
        issues.append(msg)
    ok, msg = python_version_ok()
    if not ok:
        issues.append(msg)
    ok, msg = hook_mcp_imports_ok(root)
    if not ok:
        issues.append(msg)
    return issues


def format_operator_banner(root: Optional[Path] = None) -> str:
    issues = collect_operator_issues(root)
    if not issues:
        return ""
    lines = ["\n━━━ AINL CORTEX: ACTION REQUIRED ━━━"]
    for item in issues:
        lines.append(f"  • {item}")
    lines.append("━━━\n")
    return "\n".join(lines)
