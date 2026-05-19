"""Native upgrade assessment + recommended actions for Claude Code operators."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .import_compat import plugin_root, venv_python
from .migration_compat import needs_native_migration
from .native_compat import read_store_backend


def graph_memory_has_data() -> bool:
    for db in Path.home().glob(".claude/projects/*/graph_memory/ainl_memory.db"):
        if db.stat().st_size < 8192:
            continue
        try:
            conn = sqlite3.connect(str(db))
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM ainl_graph_nodes"
                ).fetchone()
                if row and row[0] > 0:
                    return True
            except sqlite3.Error:
                if db.stat().st_size >= 8192:
                    return True
            finally:
                conn.close()
        except OSError:
            continue
    return False


def projects_needing_migration(root: Path) -> List[str]:
    out: List[str] = []
    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return out
    for proj in sorted(base.iterdir()):
        py_db = proj / "graph_memory" / "ainl_memory.db"
        if py_db.is_file() and needs_native_migration(root, py_db):
            out.append(proj.name)
    return out


def ainl_native_importable() -> bool:
    try:
        import ainl_native  # noqa: F401

        return True
    except ImportError:
        return False


def assess(root: Optional[Path] = None) -> Dict[str, Any]:
    root = root or plugin_root()
    backend = read_store_backend(root)
    has_data = graph_memory_has_data()
    native_ok = ainl_native_importable()
    rustc = shutil.which("rustc") is not None
    unmigrated = projects_needing_migration(root)

    needs_config_flip = backend == "python"
    needs_memory_migration = has_data and backend == "python"
    needs_data_copy = bool(unmigrated) or (
        backend == "native" and bool(unmigrated)
    )

    from .build_stamp import check_stale_mcp
    from .mcp_reload import check_reload_needed, read_reload_request

    stale_mcp, stale_msg = check_stale_mcp(root)
    reload_needed, reload_msg = check_reload_needed(root)
    needs_mcp_reload = stale_mcp or reload_needed

    actions: List[Dict[str, Any]] = []

    py = venv_python(root)
    if py is None:
        actions.append(
            {
                "id": "setup",
                "type": "shell",
                "command": "bash setup.sh",
                "cwd": str(root),
                "why": "Plugin venv missing — required before any upgrade.",
            }
        )
    elif backend == "native" and unmigrated:
        actions.append(
            {
                "id": "migrate_only",
                "type": "shell",
                "command": "bash scripts/migrate_python_to_native.sh",
                "cwd": str(root),
                "why": (
                    f"store_backend is native but {len(unmigrated)} project(s) still "
                    "have Python-only graph data."
                ),
            }
        )
    elif backend == "python":
        cmd = "bash scripts/upgrade_to_native.sh"
        flags: List[str] = []
        if not rustc:
            flags.append("--auto-install-rust")
        if has_data:
            flags.append("--yes")
        if flags:
            cmd += " " + " ".join(flags)
        actions.append(
            {
                "id": "upgrade",
                "type": "shell",
                "command": cmd,
                "cwd": str(root),
                "why": (
                    "Single orchestration script: ainl_native → migrate or greenfield "
                    "flip → MCP reload marker."
                ),
            }
        )
    else:
        actions.append(
            {
                "id": "noop",
                "type": "info",
                "why": "Already on native backend with no unmigrated projects.",
            }
        )

    if needs_mcp_reload or any(a["id"] in ("upgrade", "migrate_only") for a in actions):
        actions.append(
            {
                "id": "reload_plugins",
                "type": "user",
                "command": "/reload-plugins",
                "why": (
                    "Claude Code must reload MCP to pick up store_backend and new "
                    "plugin code. Hooks cannot run this slash command for you."
                ),
                "message": (
                    "After the upgrade shell commands finish successfully, ask the user "
                    "to run **/reload-plugins** in Claude Code (or fully quit and reopen). "
                    "Confirm with `/mcp` that ~30 ainl-cortex tools are listed."
                ),
            }
        )

    if stale_msg or reload_msg:
        actions.append(
            {
                "id": "stale_mcp_detail",
                "type": "info",
                "why": reload_msg or stale_msg,
            }
        )

    claude_steps = [
        f"cd {root}",
        "Run: .venv/bin/python scripts/native_upgrade_status.py  (read recommended_actions)",
        "Run the shell action(s), then tell the user to run /reload-plugins.",
        "Do NOT edit config.json by hand or call migrate_to_native.py unless debugging.",
    ]

    return {
        "plugin_root": str(root),
        "store_backend": backend,
        "ainl_native_importable": native_ok,
        "rustc_on_path": rustc,
        "graph_memory_has_data": has_data,
        "needs_config_flip": needs_config_flip,
        "needs_memory_migration": needs_memory_migration,
        "needs_data_copy": needs_data_copy,
        "unmigrated_project_hashes": unmigrated,
        "needs_mcp_reload": needs_mcp_reload,
        "recommended_actions": actions,
        "claude_playbook": claude_steps,
    }


def format_banner(state: Dict[str, Any]) -> str:
    """One-line upgrade / reload hint for SessionStart (not a full runbook box)."""
    backend = state.get("store_backend", "python")
    hints: list[str] = []

    if state.get("needs_mcp_reload"):
        hints.append("/reload-plugins (disk code ≠ running MCP)")

    if backend == "native" and state.get("unmigrated_project_hashes"):
        n = len(state["unmigrated_project_hashes"])
        hints.append(
            f"native DB empty for {n} project(s) — bash scripts/migrate_python_to_native.sh"
        )
    elif backend == "python":
        hints.append("optional native: bash scripts/claude_do_native_upgrade.sh")

    if not hints:
        return ""
    return "  • " + " · ".join(hints) + "\n"


def execute_recommended(
    root: Optional[Path] = None,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    root = root or plugin_root()
    state = assess(root)
    results: List[Dict[str, Any]] = []

    for act in state["recommended_actions"]:
        if act["type"] == "shell":
            cwd = act.get("cwd", str(root))
            cmd = act["command"]
            if dry_run:
                results.append({"id": act["id"], "dry_run": True, "command": cmd})
                continue
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
            )
            results.append(
                {
                    "id": act["id"],
                    "exit_code": proc.returncode,
                    "stdout_tail": (proc.stdout or "")[-500:],
                    "stderr_tail": (proc.stderr or "")[-500:],
                }
            )
            if proc.returncode != 0:
                state["execute_ok"] = False
                state["execute_results"] = results
                return state
        elif act["type"] == "user":
            results.append({"id": act["id"], "user_message": act.get("message", "")})
        elif act["type"] == "info":
            results.append({"id": act["id"], "info": act.get("why", "")})

    shell_results = [r for r in results if "exit_code" in r]
    if not dry_run and shell_results and all(r.get("exit_code") == 0 for r in shell_results):
        try:
            from .mcp_reload import request_mcp_reload

            request_mcp_reload(root, reason="native_upgrade_execute")
        except Exception:
            pass

    if not shell_results:
        state["execute_ok"] = True
    else:
        state["execute_ok"] = all(r.get("exit_code", 0) == 0 for r in shell_results)
    state["execute_results"] = results
    return state
