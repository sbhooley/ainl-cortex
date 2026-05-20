"""
SessionStart / agent install hints (especially Windows + Claude Code agents).

Surfaces in the SessionStart systemMessage so agents see install commands even
when they skip plugin CLAUDE.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from .hook_launcher_heal import ensure_hook_launchers, hook_launchers_healthy
from .install_bootstrap import (
    ensure_plugin_installed,
    needs_install,
    setup_ps1_is_current,
    setup_ps1_stale_message,
)
from .platform_paths import is_windows, plugin_root


def _windows_agent_command(root: Path) -> str:
    return (
        f"cd {root}; git pull; .\\setup.cmd -PythonOnly"
    )


def _unix_agent_command(root: Path) -> str:
    return f"cd {root} && git pull && bash setup.sh --python-only"


def build_agent_install_banner(
    root: Optional[Path] = None,
    *,
    mcp_ok: bool = True,
    include_auto_attempt_note: Optional[str] = None,
) -> str:
    """
  Return a prominent banner for SessionStart, or '' when install looks healthy.
    """
    root = root or plugin_root()
    reasons: list[str] = []

    if (root / "hooks" / "startup.py").is_file():
        _hooks_ok, _hooks_issue = hook_launchers_healthy(root)
        if not _hooks_ok:
            _hr_ok, _hr_msg = ensure_hook_launchers(root)
            _hooks_ok, _hooks_issue = hook_launchers_healthy(root)
            if not _hooks_ok:
                reasons.append(
                    f"hook launchers broken ({_hooks_issue}); auto-repair: {_hr_msg[:120]}"
                )

    if not setup_ps1_is_current(root) and is_windows():
        reasons.append(setup_ps1_stale_message(root))
    if needs_install(root):
        reasons.append("plugin .venv or install_manifest.json missing")
    if not mcp_ok:
        reasons.append("MCP import preflight failed")

    if not reasons:
        return ""

    lines = [
        "",
        "━━━ AINL CORTEX: AGENT INSTALL (do this for the user) ━━━",
    ]
    if include_auto_attempt_note:
        lines.append(f"  • Auto-install: {include_auto_attempt_note[:240]}")

    if is_windows():
        lines.append(f"  • Run: {_windows_agent_command(root)}")
        lines.append("  • Do NOT: & setup.ps1 -PythonOnly -Yes  (PS 5.1 parse bug)")
        lines.append("  • OK: powershell -ExecutionPolicy Bypass -File setup.ps1 -PythonOnly")
    else:
        lines.append(f"  • Run: {_unix_agent_command(root)}")
        lines.append("  • Or: python scripts/claude_install.py")

    lines.append("  • Then: user restarts Claude Code + /reload-plugins")
    lines.append("━━━")
    lines.append("")
    return "\n".join(lines)


def maybe_auto_install_at_session_start(root: Optional[Path] = None) -> Tuple[bool, str]:
    """
    Idempotent install when the venv is missing but install is otherwise safe.

    Skips when ``needs_install`` is false. Intended for SessionStart (run_hook
    may have already created .venv via uv on Windows).
    """
    root = root or plugin_root()
    if not needs_install(root):
        return True, "already installed"

    ok, msg = ensure_plugin_installed(root, python_only=True, register_claude=True)
    return ok, msg


def claude_plugin_install_blurb() -> str:
    """Short text for plugin.json description (marketplace + agent skim)."""
    return (
        " Windows install: git pull then .\\setup.cmd -PythonOnly "
        "(never & setup.ps1). SessionStart shows install steps if needed."
    )
