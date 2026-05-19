"""Compact, honest SessionStart banner fragments."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

_BENCH_RECALL = {
    "OFF": "",
    "BALANCED": "benchmark ~40–60% on recall text (varies)",
    "AGGRESSIVE": "benchmark ~60–70% on recall text (varies)",
}

_BULLET = "  • "
_CONT = "    "
_WRAP_WIDTH = 96


def _home_rel(path: Path | str) -> str:
    """Display path with ~ for home (same path, shorter line)."""
    try:
        p = Path(path).expanduser().resolve()
        rel = p.relative_to(Path.home())
        return f"~/{rel}" if str(rel) != "." else "~"
    except (ValueError, OSError):
        return str(path).replace("\n", " ")


def _shorten_venv_path_status(status: str) -> str:
    """Keep 'appended to …' wording; shorten embedded absolute paths."""
    prefix = "appended to "
    s = (status or "").replace("\n", " ").strip()
    if s.startswith(prefix):
        return prefix + _home_rel(s[len(prefix) :].strip())
    return s


def _wrap_segments(
    first_line: str,
    segments: List[str],
    *,
    sep: str = " · ",
    cont: str = _CONT,
    width: int = _WRAP_WIDTH,
) -> List[str]:
    """Break long bullets at segment boundaries with aligned continuations."""
    if not segments:
        return [first_line] if first_line else []
    lines: List[str] = []
    current = first_line + segments[0]
    for seg in segments[1:]:
        piece = sep + seg
        if len(current) + len(piece) > width:
            lines.append(current)
            current = cont + seg
        else:
            current += piece
    lines.append(current)
    return lines


def _wrap_subfield(label: str, value: str, *, indent: str = _CONT) -> List[str]:
    """Wrap long compression sub-lines at '; ' without changing labels."""
    head = f"{indent}{label}: {value}"
    if len(head) <= _WRAP_WIDTH:
        return [head]
    parts = value.split("; ")
    out = [f"{indent}{label}: {parts[0]}"]
    for part in parts[1:]:
        out.append(f"{indent}  {part}")
    return out


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
    lines: List[str] = [f"{_BULLET}Compression: {mode}"]
    if compresses:
        lines.extend(_wrap_subfield("compresses", "; ".join(compresses)))
    else:
        lines.append(f"{_CONT}compresses: (nothing — check config.json compression.*)")
    lines.extend(_wrap_subfield("not", "; ".join(not_compressed)))
    if bench:
        bench_line = f"{bench} — applies to compressed recall/prompt text only, not your whole session"
        if len(bench_line) + len(_CONT) <= _WRAP_WIDTH:
            lines.append(f"{_CONT}{bench_line}")
        else:
            lines.append(f"{_CONT}{bench}")
            lines.append(f"{_CONT}  — applies to compressed recall/prompt text only, not your whole session")

    line = "\n".join(lines) + "\n"
    return {"enabled": True, "mode": mode, "line": line, "lines": lines}


def format_stack_lines(
    *,
    ainl_ok: bool,
    ainl_heal_msg: str,
    native_status: str,
    mcp_ok: bool,
    mcp_detail: str,
    venv_file_status: str,
    bridge_line: str,
    expected_tools: int,
) -> List[str]:
    """Stack diagnostics as wrapped lines (same labels/values as the one-liner)."""
    if ainl_ok:
        ainl_bit = "yes"
    elif ainl_heal_msg:
        ainl_bit = f"no (auto-heal: {ainl_heal_msg[:80]})"
    else:
        ainl_bit = "no"
    native_bit = (native_status or "unknown").replace("\n", " ")
    mcp_bit = "OK" if mcp_ok else f"FAIL ({mcp_detail[:80]})"
    venv_bit = _shorten_venv_path_status(venv_file_status or "n/a")
    bridge_bit = (bridge_line or "n/a").replace("\n", " ")
    segments = [
        f"AINL Python tools (ainativelang)={ainl_bit}",
        f"ainl_native (Rust bindings)={native_bit}",
        f"MCP stack (same venv as server)={mcp_bit}",
        f"venv on PATH (child processes)={venv_bit}",
        f"A2A bridge={bridge_bit}",
        f"~{expected_tools} tools (ainl + memory + a2a; /mcp if missing)",
    ]
    return _wrap_segments(f"{_BULLET}Stack: ", segments)


def format_stack_one_liner(**kwargs: Any) -> str:
    """Backward-compatible single string (joined with newlines)."""
    return "\n".join(format_stack_lines(**kwargs))


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
    lines: List[str] = [f"[AINL Cortex]  {_home_rel(root)}"]
    graph_segments = [
        f"Graph Memory: {db_s}",
        f"backend: {backend}",
        f"project: {project_id} ({isolation_mode}, {git_bit})",
        f"cwd: {_home_rel(cwd)}",
    ]
    lines.extend(
        _wrap_segments(f"{_BULLET}", graph_segments, sep="  |  ", cont=_CONT + "|  ")
    )
    if legacy_project_id and project_id != legacy_project_id:
        lines.append(f"{_BULLET}Legacy fallback: {legacy_project_id}")
        lines.append(f"{_CONT}(read-only until backfill via scripts/repartition_by_repo.py)")
    if recall_line:
        lines.append(recall_line.rstrip("\n"))

    if compression_lines:
        for cl in compression_lines:
            lines.append(cl.rstrip("\n"))
    elif compression_line:
        for cl in compression_line.split("\n"):
            if cl.strip():
                lines.append(cl.rstrip("\n"))

    lines.extend(
        format_stack_lines(
            ainl_ok=ainl_ok,
            ainl_heal_msg=ainl_heal_msg,
            native_status=native_status,
            mcp_ok=mcp_ok,
            mcp_detail=mcp_detail,
            venv_file_status=venv_file_status,
            bridge_line=bridge_line,
            expected_tools=expected_tools,
        )
    )
    lines.extend(
        _wrap_segments(
            f"{_BULLET}After git pull or setup.sh: run /reload-plugins if tools act stale",
            ["(/plugin → Installed → ainl-cortex)."],
            sep=" ",
            cont=_CONT,
        )
    )
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
