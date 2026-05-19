"""Compact, honest SessionStart banner fragments."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


def compression_status_from_config() -> Dict[str, Any]:
    """Return compression mode + honest savings wording (benchmark, not guaranteed)."""
    try:
        from config import get_config

        config = get_config()
        mode = config.get_compression_mode().name
        enabled = config.is_compression_enabled()
    except Exception:
        mode, enabled = "AGGRESSIVE", True

    notes = {
        "OFF": "off",
        "BALANCED": "est. 40–60% fewer tokens on recall injections (benchmark; varies)",
        "AGGRESSIVE": "est. 60–70% fewer tokens on recall injections (benchmark; varies)",
    }
    if not enabled or mode == "OFF":
        return {"enabled": False, "mode": "OFF", "line": "  • Compression: off\n"}
    note = notes.get(mode, "typical savings vary by session")
    return {
        "enabled": True,
        "mode": mode,
        "line": f"  • Compression: {mode} — {note}\n",
    }


def build_main_banner(
    *,
    root: Path,
    backend: str,
    db_s: str,
    project_id: str,
    isolation_mode: str,
    git_repo: bool,
    compression_line: str,
    ainl_ok: bool,
    mcp_ok: bool,
    mcp_detail: str,
    native_status: str,
    expected_tools: int,
    a2a_enabled: bool,
    bridge_running: bool,
    bridge_reason: str,
    recall_line: str = "",
) -> str:
    """Short status block — no duplicate tildes, no path dumps."""
    git_bit = "git" if git_repo else "no-git"
    lines = [
        f"[AINL Cortex]  {root}",
        f"  • Memory: {db_s}  |  backend: {backend}  |  project: {project_id} ({isolation_mode}, {git_bit})",
    ]
    if recall_line:
        lines.append(recall_line.rstrip("\n"))

    stack = [f"ainativelang: {'ok' if ainl_ok else 'missing'}"]
    stack.append(f"MCP: {'OK' if mcp_ok else 'FAIL'}")
    if backend == "native":
        stack.append(f"native: {native_status[:40]}")
    elif "ok" in native_status.lower() or "installed" in native_status.lower():
        stack.append("ainl_native: ready (optional upgrade)")
    lines.append(f"  • Stack: {' · '.join(stack)}  |  ~{expected_tools} tools (/mcp)")

    lines.append(compression_line.rstrip("\n"))

    if a2a_enabled:
        if bridge_running:
            lines.append("  • A2A: running")
        else:
            short = (bridge_reason or "offline")[:80]
            lines.append(f"  • A2A: offline ({short})")

    if not mcp_ok:
        lines.append(f"  • MCP detail: {mcp_detail[:120]}")

    lines.append("  • After git pull or setup.sh: run /reload-plugins if tools act stale.")
    return "\n".join(lines) + "\n"


def format_upgrade_hint(state: Dict[str, Any]) -> str:
    """One-line upgrade / reload hint — not a full runbook box."""
    backend = state.get("store_backend", "python")
    hints: list[str] = []

    if state.get("needs_mcp_reload"):
        hints.append("/reload-plugins (disk code ≠ running MCP)")

    if backend == "native" and state.get("unmigrated_project_hashes"):
        n = len(state["unmigrated_project_hashes"])
        hints.append(f"native DB empty for {n} project(s) — bash scripts/migrate_python_to_native.sh")
    elif backend == "python":
        hints.append("optional native: bash scripts/claude_do_native_upgrade.sh")

    if not hints:
        return ""
    return "  • " + " · ".join(hints) + "\n"


def format_prior_session_brief(
    summary: Dict[str, Any],
    *,
    age_str: str,
    freshness: str,
    can_execute: bool,
) -> str:
    """Two lines max for prior-session context."""
    task = (summary.get("task_summary") or "—").strip()
    if len(task) > 100:
        task = task[:97] + "…"
    outcome = summary.get("outcome", "?")
    line = f"  • Prior session ({age_str}): {task} — outcome: {outcome}"
    if not can_execute:
        line += f" (freshness: {freshness}; refresh before relying on this)"
    return line + "\n"
