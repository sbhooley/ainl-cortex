"""Compact, honest SessionStart banner fragments."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

_BENCH_RECALL = {
    "OFF": "",
    "BALANCED": "benchmark ~40–60% on recall text (varies)",
    "AGGRESSIVE": "benchmark ~60–70% on recall text (varies)",
}


def _output_compression_enabled(config: Any) -> bool:
    try:
        out = config._compression_nested("output")
        return bool(
            config.is_compression_enabled()
            and out.get("enabled", False)
        )
    except Exception:
        return False


def _compression_flags_from_raw(raw: Dict[str, Any]) -> tuple[str, bool, bool, bool, bool, int]:
    """Parse config.json compression block without PluginConfig (hook-safe)."""
    comp = raw.get("compression") if isinstance(raw.get("compression"), dict) else {}
    enabled = bool(comp.get("enabled", True))
    mode_str = str(comp.get("mode", "balanced")).strip().lower()
    if mode_str in ("off", "none", "disabled", "0", "false"):
        return "OFF", False, False, False, False, int(comp.get("min_tokens_for_compression", 80))
    mode = mode_str.upper()
    if mode not in ("BALANCED", "AGGRESSIVE"):
        mode = "BALANCED"
    mem = enabled and bool(comp.get("compress_memory_context", True))
    user = enabled and bool(comp.get("compress_user_prompt", True))
    out_block = comp.get("output") if isinstance(comp.get("output"), dict) else {}
    output = enabled and bool(out_block.get("enabled", comp.get("compress_output", False)))
    min_tok = int(comp.get("min_tokens_for_compression", 80) or 80)
    return mode, enabled, mem, user, output, min_tok


def compression_status_from_config() -> Dict[str, Any]:
    """Compression mode plus what eco mode does and does not touch."""
    mode = "OFF"
    enabled = False
    mem = False
    user = False
    output = False
    min_tok = 80

    try:
        from mcp_server.config import get_config

        config = get_config()
        mode = config.get_compression_mode().name
        enabled = config.is_compression_enabled()
        mem = config.should_compress_memory_context()
        user = config.should_compress_user_prompt()
        output = _output_compression_enabled(config)
        min_tok = config.get_min_tokens_for_compression()
    except Exception:
        try:
            from shared.config import read_config

            mode, enabled, mem, user, output, min_tok = _compression_flags_from_raw(
                read_config()
            )
        except Exception:
            mode, enabled, mem, user, output, min_tok = "BALANCED", True, True, True, False, 80

    if not enabled or mode == "OFF":
        off = "  • Compression: off (graph recall and prompts sent verbatim)\n"
        return {"enabled": False, "mode": "OFF", "line": off, "lines": [off.rstrip("\n")]}

    compresses: List[str] = []
    if mem:
        compresses.append("graph-memory recall brief (injected before each prompt)")
    if user:
        compresses.append(f"long user prompts (≥~{min_tok} tokens)")
    if output:
        compresses.append("assistant replies (output eco)")

    not_compressed = [
        "SQLite graph store on disk",
        "MCP tool definitions & tool results",
        "Claude Code chat transcript / compaction",
    ]
    if not output:
        not_compressed.append("assistant replies (output eco off)")

    bench = _BENCH_RECALL.get(mode, "savings vary by session")
    lines: List[str] = [f"  • Compression: {mode}"]
    if compresses:
        lines.append(f"    compresses: {'; '.join(compresses)}")
    else:
        lines.append("    compresses: (nothing — check config.json compression.*)")
    lines.append(f"    not: {'; '.join(not_compressed)}")
    if bench:
        lines.append(f"    {bench} — applies to compressed recall/prompt text only, not your whole session")

    line = "\n".join(lines) + "\n"
    return {"enabled": True, "mode": mode, "line": line, "lines": lines}


def build_main_banner(
    *,
    root: Path,
    backend: str,
    db_s: str,
    project_id: str,
    isolation_mode: str,
    git_repo: bool,
    cwd: Path,
    legacy_project_id: str = "",
    compression_line: str = "",
    compression_lines: Optional[List[str]] = None,
    ainl_ok: bool,
    ainl_heal_msg: str = "",
    mcp_ok: bool,
    mcp_detail: str,
    native_status: str,
    venv_file_status: str = "",
    expected_tools: int,
    bridge_line: str = "",
    recall_line: str = "",
) -> str:
    """SessionStart status block (graph memory, stack health, compression)."""
    git_bit = "git" if git_repo else "no-git"
    lines = [
        f"[AINL Cortex]  {root}",
        (
            f"  • Graph Memory: {db_s}  |  backend: {backend}  |  "
            f"project: {project_id} ({isolation_mode}, {git_bit})  cwd: {cwd}"
        ),
    ]
    if legacy_project_id and project_id != legacy_project_id:
        lines.append(
            f"  • Legacy fallback: {legacy_project_id} "
            f"(read-only until backfill via scripts/repartition_by_repo.py)"
        )
    if recall_line:
        lines.append(recall_line.rstrip("\n"))

    if compression_lines:
        for cl in compression_lines:
            lines.append(cl.rstrip("\n"))
    elif compression_line:
        for cl in compression_line.split("\n"):
            if cl.strip():
                lines.append(cl.rstrip("\n"))

    if ainl_ok:
        ainl_bit = "yes"
    elif ainl_heal_msg:
        ainl_bit = f"no (auto-heal: {ainl_heal_msg[:120]})"
    else:
        ainl_bit = "no"
    lines.append(f"  • AINL Python tools (ainativelang): {ainl_bit}")
    lines.append(f"  • ainl_native (Rust bindings): {native_status}")
    mcp_bit = "OK" if mcp_ok else f"FAIL – {mcp_detail[:100]}"
    lines.append(f"  • MCP stack (same venv as server): {mcp_bit}")
    if venv_file_status:
        lines.append(f"  • venv on PATH (child processes): {venv_file_status}")
    if bridge_line:
        lines.append(f"  • A2A bridge: {bridge_line}")
    lines.append(
        f"  • When Claude spawns MCP, expect ~{expected_tools} tools (ainl + memory + a2a); "
        f"if missing, /plugin -> Installed -> ainl-cortex and /mcp, or /reload-plugins."
    )
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


def format_prior_session_context(
    summary: Dict[str, Any],
    *,
    age_str: str,
    freshness: str,
    can_execute: bool,
) -> str:
    """Prior-session anchored summary box for SessionStart."""
    lines = [f"\n━━━ PRIOR SESSION CONTEXT ({age_str}) ━━━"]
    lines.append(f"  Summary: {summary.get('task_summary', '—')}")
    lines.append(
        f"  Outcome: {summary.get('outcome', '?')}  |  "
        f"Captures: {summary.get('capture_count', 0)}"
    )
    if summary.get("tools_used"):
        lines.append(f"  Tools: {', '.join(summary['tools_used'][:8])}")
    if summary.get("files_touched"):
        lines.append(f"  Files: {', '.join(summary['files_touched'][:6])}")
    if summary.get("semantic_tags"):
        lines.append(f"  Tags: {', '.join(summary['semantic_tags'][:5])}")
    exec_note = "yes" if can_execute else "refresh recommended"
    lines.append(f"  Context freshness: {freshness} (execute: {exec_note})")
    last_finalize = summary.get("last_finalize") or {}
    if last_finalize:
        lines.append(
            f"  Persisted: {last_finalize.get('trajectory_steps', 0)} traj steps, "
            f"{last_finalize.get('procedures_promoted', 0)} procedures promoted"
        )
    lines.append("━━━ END PRIOR SESSION ━━━\n")
    return "\n".join(lines)


def format_prior_session_brief(
    summary: Dict[str, Any],
    *,
    age_str: str,
    freshness: str,
    can_execute: bool,
) -> str:
    """Compact prior-session line (used when full box is disabled)."""
    task = (summary.get("task_summary") or "—").strip()
    if len(task) > 100:
        task = task[:97] + "…"
    outcome = summary.get("outcome", "?")
    line = f"  • Prior session ({age_str}): {task} — outcome: {outcome}"
    if not can_execute:
        line += f" (freshness: {freshness}; refresh before relying on this)"
    return line + "\n"
