"""Native upgrade assessment + recommended actions for Claude Code operators."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .import_compat import plugin_root, venv_python
from .platform_paths import is_windows
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
        setup_cmd = (
            "powershell -ExecutionPolicy Bypass -File setup.ps1"
            if is_windows()
            else "bash setup.sh"
        )
        actions.append(
            {
                "id": "setup",
                "type": "shell",
                "command": setup_cmd,
                "cwd": str(root),
                "why": "Plugin venv missing — required before any upgrade.",
            }
        )
    elif backend == "native" and unmigrated:
        if py:
            actions.append(
                {
                    "id": "migrate_only",
                    "type": "python_script",
                    "script": "scripts/migrate_python_to_native.py",
                    "args": ["--yes"],
                    "cwd": str(root),
                    "why": (
                        f"store_backend is native but {len(unmigrated)} project(s) still "
                        "have Python-only graph data."
                    ),
                }
            )
        elif is_windows():
            actions.append(
                {
                    "id": "migrate_only",
                    "type": "shell",
                    "command": (
                        "powershell -ExecutionPolicy Bypass -File "
                        "scripts/migrate_python_to_native.ps1 --yes"
                    ),
                    "cwd": str(root),
                    "why": (
                        f"store_backend is native but {len(unmigrated)} project(s) still "
                        "have Python-only graph data."
                    ),
                }
            )
        else:
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
        flags: List[str] = []
        if not rustc:
            flags.append("--auto-install-rust")
        if has_data:
            flags.append("--yes")
        flag_s = (" " + " ".join(flags)) if flags else ""
        if is_windows():
            ps_flags = []
            if has_data:
                ps_flags.append("-Yes")
            if not rustc:
                ps_flags.append("-AutoInstallRust")
            ps_suffix = (" " + " ".join(ps_flags)) if ps_flags else ""
            cmd = f"powershell -ExecutionPolicy Bypass -File scripts/upgrade_to_native.ps1{ps_suffix}"
        elif py is not None:
            cmd = f'"{py}" scripts/upgrade_to_native.py{flag_s}'
        else:
            cmd = f"python scripts/upgrade_to_native.py{flag_s}"
        actions.append(
            {
                "id": "upgrade",
                "type": "shell",
                "command": cmd,
                "cwd": str(root),
                "why": (
                    "ainl_native (PyPI wheel on Windows) → migrate or greenfield flip → "
                    "MCP reload marker."
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

    status_py = f'"{py}" scripts/native_upgrade_status.py' if py else "python scripts/native_upgrade_status.py"
    claude_steps = [
        f"cd {root}",
        f"Run: {status_py}  (read recommended_actions)",
        "Run the shell action(s), then tell the user to run /reload-plugins.",
        "Do NOT edit config.json by hand unless debugging.",
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
    """SessionStart upgrade runbook box (backend status + recommended actions)."""
    lines = [
        "\n━━━ AINL CORTEX: CLAUDE CODE UPGRADE RUNBOOK ━━━",
        f"  • Backend: {state['store_backend']}  |  graph data: "
        f"{'yes' if state['graph_memory_has_data'] else 'no'}  |  "
        f"ainl_native: {'ok' if state['ainl_native_importable'] else 'missing'}",
    ]
    if state.get("unmigrated_project_hashes"):
        lines.append(
            f"  • Unmigrated projects: {', '.join(state['unmigrated_project_hashes'][:5])}"
            + (" …" if len(state["unmigrated_project_hashes"]) > 5 else "")
        )
    for act in state["recommended_actions"]:
        if act["type"] == "shell":
            lines.append(f"  • RUN: {act['command']}  ({act['id']})")
        elif act["type"] == "python_script":
            args_s = " ".join(act.get("args") or [])
            lines.append(f"  • RUN: {act.get('script', '')} {args_s}  ({act['id']})".strip())
        elif act["type"] == "user":
            lines.append(f"  • USER: {act.get('command', '/reload-plugins')}")
    py = venv_python(Path(state["plugin_root"]))
    status_cmd = (
        f'"{py}" scripts/native_upgrade_status.py --execute'
        if py
        else "python scripts/native_upgrade_status.py --execute"
    )
    lines.append(f"  • Agent: {status_cmd} when the user asks to upgrade to native.")
    lines.append("━━━\n")
    return "\n".join(lines)


def _run_python_script_action(
    root: Path,
    act: Dict[str, Any],
) -> subprocess.CompletedProcess[str]:
    py = venv_python(root)
    if py is None:
        raise RuntimeError("Plugin venv missing — run setup.sh or setup.ps1")
    script = root / act["script"]
    args = [str(a) for a in act.get("args") or []]
    return subprocess.run(
        [str(py), str(script), *args],
        cwd=act.get("cwd", str(root)),
        capture_output=True,
        text=True,
        check=False,
    )


def execute_recommended(
    root: Optional[Path] = None,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    root = root or plugin_root()
    state = assess(root)
    results: List[Dict[str, Any]] = []
    state.setdefault("execute_ok", True)

    for act in state["recommended_actions"]:
        if act["type"] == "python_script":
            cwd = act.get("cwd", str(root))
            label = f"{act.get('script', '')} {' '.join(act.get('args') or [])}".strip()
            if dry_run:
                results.append({"id": act["id"], "dry_run": True, "command": label})
                continue
            try:
                proc = _run_python_script_action(root, act)
            except RuntimeError as e:
                results.append({"id": act["id"], "exit_code": 1, "stderr_tail": str(e)})
                state["execute_ok"] = False
                state["execute_results"] = results
                return state
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
        elif act["type"] == "shell":
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
