"""
Unified runtime bootstrap for MCP and hooks.

Call ``bootstrap_runtime()`` at install, MCP launch, package import, SessionStart,
and before tool dispatch.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

from . import build_stamp, deps_compat, import_compat, native_compat, operator_checks

logger = logging.getLogger(__name__)

_bootstrapped_full = False


def bootstrap_runtime(
    root: Optional[Path] = None,
    *,
    quick: bool = False,
    heal_deps: bool = True,
    record_mcp_runtime: bool = False,
) -> Tuple[bool, str]:
    """
    Run self-healing preflight. Never raises.

    ``quick=True`` — path + module shims only (tool dispatch hot path).
    """
    global _bootstrapped_full
    root = root or import_compat.plugin_root()
    import_compat.ensure_sys_path(root)
    import_compat.ensure_hooks_path(root)

    shims_ok = import_compat.ensure_mcp_module_shims()
    parts = [f"shims={'ok' if shims_ok else 'partial'}"]

    if quick:
        return shims_ok, "; ".join(parts)

    try:
        from .hook_launcher_heal import ensure_hook_launchers

        _h_ok, _h_msg = ensure_hook_launchers(root)
        if _h_msg.startswith("repaired:"):
            parts.append(_h_msg)
    except Exception:
        pass

    if heal_deps:
        ainl_ok, ainl_msg = deps_compat.ensure_ainativelang(root)
        parts.append(f"ainativelang={'ok' if ainl_ok else ainl_msg}")
        if native_compat.read_store_backend(root) == "native":
            nat_ok, nat_msg = native_compat.ensure_ainl_native(root)
            parts.append(f"ainl_native={'ok' if nat_ok else nat_msg}")

    if record_mcp_runtime:
        sha = build_stamp.write_mcp_runtime_stamp(root)
        if sha:
            parts.append(f"mcp_runtime={sha[:8]}")

    _bootstrapped_full = True
    ok = shims_ok and (not heal_deps or deps_compat.ainativelang_importable())
    return ok, "; ".join(parts)


def heal_tool_import_error(exc: BaseException) -> bool:
    """Retry path for tool handlers after import/heal."""
    if import_compat.heal_import_error(exc):
        return True
    if import_compat.is_mcp_import_error(exc):
        return import_compat.ensure_mcp_module_shims(force=True)
    return False


def ensure_ainl_tools_on_server(memory_server) -> bool:
    """Attach AINLTools to server after pip heal."""
    if memory_server.ainl_tools is not None:
        return True
    tools = deps_compat.create_ainl_tools_if_possible(memory_server.db_path)
    if tools is not None:
        memory_server.ainl_tools = tools
        logger.info("AINL tools auto-healed and attached")
        return True
    return False


def session_start_extras(root: Optional[Path] = None) -> dict:
    """Extra banner fragments for SessionStart."""
    root = root or import_compat.plugin_root()
    from .build_stamp import check_stale_mcp
    from .mcp_reload import check_reload_needed, read_reload_request
    from .migration_compat import scan_and_auto_migrate_all_projects

    stale, stale_msg = check_stale_mcp(root)
    reload_needed, reload_msg = check_reload_needed(root)
    operator_banner = operator_checks.format_operator_banner(root)

    migrate_ran, migrate_msg = scan_and_auto_migrate_all_projects(root)

    upgrade_banner = ""
    try:
        from .native_upgrade_runbook import assess, format_banner

        upgrade_banner = format_banner(assess(root))
    except Exception:
        pass

    return {
        "stale_mcp": stale or reload_needed,
        "stale_mcp_message": reload_msg or stale_msg,
        "operator_banner": operator_banner,
        "upgrade_runbook_banner": upgrade_banner,
        "auto_migrate_ran": migrate_ran,
        "auto_migrate_message": migrate_msg,
        "reload_requested": read_reload_request(root) is not None,
    }
