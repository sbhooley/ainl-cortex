"""Self-heal Claude Code wiring for new installs (no manual sync scripts).

Fixes stale ``installed_plugins.json`` cache paths, wrong MCP launcher command,
missing marketplace registration, and missing ``ainativelang`` in the venv.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from . import deps_compat
from .import_compat import plugin_root
from .install_bootstrap import is_safe_install_root
from .platform_paths import canonical_plugin_root, is_windows, venv_python

logger = logging.getLogger(__name__)

PLUGIN_KEY = "ainl-cortex@ainl-local"


def _installed_plugins_path() -> Path:
    return Path.home() / ".claude" / "plugins" / "installed_plugins.json"


def installed_plugins_needs_sync(root: Path) -> Tuple[bool, str]:
    """True when Claude may load a stale or missing plugin directory."""
    root = root.resolve()
    path = _installed_plugins_path()
    if not path.is_file():
        return True, "installed_plugins.json missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True, "installed_plugins.json unreadable"

    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        return True, "installed_plugins.json has no plugins map"

    entries = plugins.get(PLUGIN_KEY)
    if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
        return True, f"{PLUGIN_KEY} not registered"

    install_path = entries[0].get("installPath")
    if not install_path:
        return True, "installPath empty"

    resolved = str(root)
    if str(install_path) != resolved:
        return True, f"installPath mismatch ({install_path} != {resolved})"

    if "/plugins/cache/" in str(install_path).replace("\\", "/"):
        return True, "installPath still points at marketplace cache"

    if not Path(install_path).is_dir():
        return True, f"installPath missing on disk ({install_path})"

    return False, "ok"


def mcp_launcher_needs_update(root: Path) -> Tuple[bool, str]:
    """True when plugin.json MCP command would launch the wrong interpreter."""
    path = root / ".claude-plugin" / "plugin.json"
    if not path.is_file():
        return False, "no plugin.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True, "plugin.json unreadable"

    entry = (data.get("mcpServers") or {}).get("ainl-cortex")
    if not isinstance(entry, dict):
        return True, "mcpServers.ainl-cortex missing"

    if is_windows():
        want_cmd, want_args = "cmd", ["/c", "${CLAUDE_PLUGIN_ROOT}/mcp_launch.cmd"]
    else:
        want_cmd, want_args = "python3", ["${CLAUDE_PLUGIN_ROOT}/mcp_launch.py"]

    if entry.get("command") != want_cmd:
        return True, f"command={entry.get('command')!r} want {want_cmd!r}"
    if entry.get("args") != want_args:
        return True, "args mismatch for mcp_launch"
    if entry.get("cwd") != "${CLAUDE_PLUGIN_ROOT}":
        return True, "cwd not ${CLAUDE_PLUGIN_ROOT}"
    return False, "ok"


def settings_need_registration() -> Tuple[bool, str]:
    path = Path.home() / ".claude" / "settings.json"
    if not path.is_file():
        return True, "settings.json missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True, "settings.json unreadable"
    enabled = data.get("enabledPlugins") if isinstance(data, dict) else None
    if not isinstance(enabled, dict) or not enabled.get(PLUGIN_KEY):
        return True, f"{PLUGIN_KEY} not enabled"
    markets = data.get("extraKnownMarketplaces") if isinstance(data, dict) else None
    if not isinstance(markets, dict) or "ainl-local" not in markets:
        return True, "ainl-local marketplace not registered"
    return False, "ok"


def heal_claude_integration(root: Optional[Path] = None) -> Tuple[bool, List[str]]:
    """
    Idempotent fixes for new-user install gaps.

    Returns (reload_recommended, action_messages).
    """
    running_root = (root or plugin_root()).resolve()
    root = canonical_plugin_root(running_root)
    actions: List[str] = []
    reload = False

    if root != running_root:
        actions.append(f"live plugin path {root} (Claude was using cache {running_root})")

    if not is_safe_install_root(root):
        return False, ["skipped claude integration heal (ephemeral plugin path)"]

    # 1. Venv + ainativelang (pip package → compiler_v2 import)
    if venv_python(root) is None:
        actions.append("venv missing — run auto-install from MCP/hooks")
    else:
        ok, msg = deps_compat.ensure_ainativelang(root)
        if ok and deps_compat.ainativelang_importable():
            ver = deps_compat.ainativelang_pip_version()
            if msg and msg != "ainativelang already importable":
                actions.append(f"ainativelang: {msg}" + (f" ({ver})" if ver else ""))
        else:
            actions.append(f"ainativelang heal failed: {msg}")

    # 2. Claude settings + marketplace
    need_reg, reg_reason = settings_need_registration()
    if need_reg:
        try:
            from scripts.configure_marketplace import ensure_local_marketplace
            from scripts.register_claude_settings import register

            mp = ensure_local_marketplace(root)
            register(Path.home() / ".claude" / "settings.json", mp)
            actions.append(f"registered Claude settings ({reg_reason})")
            reload = True
        except Exception as exc:
            actions.append(f"settings registration failed: {exc}")
    else:
        need_sync, sync_reason = installed_plugins_needs_sync(root)
        if need_sync:
            try:
                from scripts.sync_installed_plugins import sync_installed_plugins

                changed, msg = sync_installed_plugins(root)
                actions.append(f"installed_plugins: {msg}")
                if changed:
                    reload = True
            except Exception as exc:
                actions.append(f"installed_plugins sync failed: {exc}")

    # 3. MCP launcher in plugin.json
    need_mcp, mcp_reason = mcp_launcher_needs_update(root)
    if need_mcp:
        try:
            from .mcp_launcher_config import configure_mcp_launcher

            configure_mcp_launcher(root)
            actions.append(f"MCP launcher repaired ({mcp_reason})")
            reload = True
        except Exception as exc:
            actions.append(f"MCP launcher repair failed: {exc}")

    if reload:
        try:
            from .mcp_reload import request_mcp_reload

            request_mcp_reload(root, reason="claude_integration_heal")
        except Exception:
            pass

    if actions:
        logger.info("claude_integration_heal: %s", "; ".join(actions))
    return reload, actions


def format_heal_banner(reload: bool, actions: List[str]) -> str:
    if not actions:
        return ""
    lines = ["\n━━━ AINL CORTEX: AUTO-HEAL ━━━"]
    for item in actions[:8]:
        lines.append(f"  • {item}")
    if reload:
        lines.append("  • Run /reload-plugins once (Claude Code) to apply wiring fixes")
    lines.append("━━━\n")
    return "\n".join(lines)
