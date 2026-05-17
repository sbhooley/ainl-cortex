#!/usr/bin/env python3
"""
SessionStart: visible status for Claude (systemMessage) + preflight DB/venv/MCP.
Claude Code shows stderr from hooks inconsistently; always emit JSON on stdout with
systemMessage + hookSpecificOutput (see plugin-dev hook-development SKILL).
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
_mcp_dir = str(Path(__file__).resolve().parent.parent / "mcp_server")
if _mcp_dir not in sys.path:
    sys.path.insert(0, _mcp_dir)

from shared.logger import get_logger
from shared.project_id import get_project_id, get_project_info, get_git_branch, LEGACY_GLOBAL_PROJECT_ID
from shared.a2a_inbox import read_self_inbox, clear_self_inbox
from notifications import poll as _poll_notifications, format_banner as _format_notif_banner

try:
    import ainl_native as _ainl_native
    _NATIVE_OK = True
except ImportError:
    _ainl_native = None
    _NATIVE_OK = False

logger = get_logger("startup")

TOOL_COUNT_MEMORY = 21  # 7 core + session_history + evolve_persona + expand_node + 4 goals + 5 autonomous + executions audit + begin_task_execution + approve_task
TOOL_COUNT_AINL = 12
TOOL_COUNT_A2A = 7
EXPECTED_MCP_TOOLS = TOOL_COUNT_MEMORY + TOOL_COUNT_AINL + TOOL_COUNT_A2A


def _plugin_root() -> Path:
    p = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if p:
        return Path(p).resolve()
    return Path(__file__).resolve().parent.parent


def _hook_cwd() -> Path:
    try:
        from shared.stdin import read_stdin_json
        data = read_stdin_json(hook_name="startup")
        c = data.get("cwd")
        if c:
            return Path(c)
    except Exception:
        pass
    return Path.cwd()


def get_compression_status():
    try:
        from config import get_config
        from compression import EfficientMode

        config = get_config()
        m = config.get_compression_mode()
        mode = m.name
        enabled = config.is_compression_enabled()
        savings_map = {
            "OFF": "0%",
            "BALANCED": "~40–60%",
            "AGGRESSIVE": "~60–70%",
        }
        savings = savings_map.get(mode) or savings_map.get(m.value.upper(), "~60–70%")
        return {
            "enabled": enabled,
            "mode": mode,
            "savings": savings,
        }
    except Exception as e:
        logger.error("get_compression_status: %s", e)
        return {
            "enabled": True,
            "mode": "AGGRESSIVE",
            "savings": "~60–70%",
        }


def check_ainl_tools() -> bool:
    try:
        from ainl_tools import AINLTools  # noqa: F401
        return True
    except ImportError:
        return False


def get_db_path(cwd: Path) -> Path:
    project_hash = get_project_id(cwd)
    memory_dir = Path.home() / ".claude" / "projects" / project_hash / "graph_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir / "ainl_memory.db"


def warm_database(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("SELECT 1")
    finally:
        conn.close()
    return f"ready ({db_path.name})"


def _venv_python(plugin_root: Path) -> Optional[Path]:
    bindir = plugin_root / ".venv" / "bin"
    for name in ("python", "python3", "python3.14", "python3.12", "python3.11"):
        p = bindir / name
        if p.is_file() and os.access(p, os.X_OK):
            return p
    return None


def _env_for_mcp_test(plugin_root: Path) -> dict:
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin_root)}
    parts = [str(plugin_root)]
    for lib in (plugin_root / ".venv" / "lib").glob("python*"):
        sitep = lib / "site-packages"
        if sitep.is_dir():
            parts.append(str(sitep))
            break
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def verify_mcp_imports(plugin_root: Path) -> Tuple[bool, str]:
    """
    Resolves a Python that can import mcp (venv binary preferred; else system
    python3 + venv site-packages — same strategy as mcp_launch.sh).
    """
    pycheck = "import mcp.server; import mcp_server.graph_store; import mcp_server.server"
    tried: list[str] = []
    py = _venv_python(plugin_root)
    if py:
        tried.append(str(py))
        env = _env_for_mcp_test(plugin_root)
        r = subprocess.run(
            [str(py), "-c", pycheck],
            cwd=str(plugin_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            return True, f"venv: {py.name} OK"
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()[:200]
            tried.append(f"({err})")
    for pyname in ("python3", "python3.14", "python3.12", "python3.11"):
        w = shutil.which(pyname)
        if w:
            tried.append(w)
            env = _env_for_mcp_test(plugin_root)
            r = subprocess.run(
                [w, "-c", pycheck],
                cwd=str(plugin_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode == 0:
                return True, f"system {pyname} + venv site-packages OK"
    return False, f"tried: {'; '.join(tried)} (install/venv issue)"


def append_venv_to_envfile(plugin_root: Path) -> str:
    fe = os.environ.get("CLAUDE_ENV_FILE")
    if not fe:
        return "CLAUDE_ENV_FILE not set (optional)"
    try:
        line = f'\n# ainl-cortex (SessionStart)\nexport PATH="{plugin_root / ".venv" / "bin"}:$PATH"\n'
        line += f'export PYTHONPATH="{plugin_root}:$PYTHONPATH"\n'
        with open(fe, "a", encoding="utf-8") as f:
            f.write(line)
        return f"appended to {fe}"
    except OSError as e:
        return f"could not write CLAUDE_ENV_FILE: {e}"


def _ensure_ainl_native(plugin_root: Path) -> str:
    """
    Ensure ainl_native Rust extension is built and installed.
    Returns a short status string for the banner.
    """
    try:
        import importlib.util
        spec = importlib.util.find_spec("ainl_native")
        if spec is not None:
            return "ok (already installed)"
    except Exception:
        pass

    native_dir = plugin_root / "ainl_native"
    if not native_dir.is_dir():
        return "skipped (ainl_native/ directory not found)"

    py = _venv_python(plugin_root)
    if py is None:
        return "skipped (no venv python)"

    maturin = plugin_root / ".venv" / "bin" / "maturin"
    if not maturin.is_file():
        try:
            r = subprocess.run(
                [str(py), "-m", "pip", "install", "maturin", "--quiet"],
                capture_output=True, text=True, timeout=120,
            )
        except Exception as e:
            return f"could not install maturin: {e}"

    try:
        env = {**os.environ, "PYO3_USE_ABI3_FORWARD_COMPATIBILITY": "1"}
        r = subprocess.run(
            [str(maturin), "develop", "--release", "--manifest-path", str(native_dir / "Cargo.toml")],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(plugin_root),
        )
        if r.returncode == 0:
            return "built + installed"
        else:
            err = (r.stderr or r.stdout or "").strip()[-200:]
            return f"build failed: {err}"
    except subprocess.TimeoutExpired:
        return "build timed out (>5 min)"
    except Exception as e:
        return f"build error: {e}"


def main():
    try:
        _ss_t0 = time.perf_counter()
        root = _plugin_root()
        cwd = _hook_cwd()
        logger.info("SessionStart: plugin=%s cwd=%s", root, cwd)

        status = get_compression_status()
        ainl = check_ainl_tools()
        db_path = get_db_path(cwd)
        try:
            db_s = warm_database(db_path)
        except OSError as e:
            db_s = f"error: {e}"

        # Generate and persist a session UUID for audit delta tracking
        try:
            from shared.session_delta import write_session_id
            _project_id_for_sid = get_project_id(cwd)
            write_session_id(_project_id_for_sid, root)
        except Exception:
            pass

        mcp_ok, mcp_detail = verify_mcp_imports(root)
        # Only attempt native build when config explicitly requests it
        try:
            import json as _json
            _backend = _json.loads((root / "config.json").read_text()).get("memory", {}).get("store_backend", "python")
        except Exception:
            _backend = "python"
        if _backend == "native":
            native_status = _ensure_ainl_native(root)
            # Detect unmigrated data: native configured but native DB empty while Python DB has data
            try:
                _native_db = db_path.parent / "ainl_native.db"
                _py_db = db_path  # ainl_memory.db
                if _py_db.exists() and _py_db.stat().st_size > 8192:
                    import sqlite3 as _sq
                    if not _native_db.exists():
                        _native_empty = True
                    else:
                        _conn = _sq.connect(str(_native_db))
                        try:
                            _native_empty = _conn.execute(
                                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                            ).fetchone()[0] == 0
                        finally:
                            _conn.close()
                    if _native_empty:
                        native_status += " — ⚠️  unmigrated data detected: re-run setup.sh to migrate"
            except Exception:
                pass
        else:
            native_status = "skipped (python backend selected)"
        venv_file_status = append_venv_to_envfile(root)

        # ── Telemetry ─────────────────────────────────────────────────────────
        try:
            from telemetry import capture as _tel_capture
            import json as _tel_json
            _tel_cfg = _tel_json.loads((root / "config.json").read_text())
            _tel_capture("session_start", {"backend": _backend}, root)
        except Exception:
            pass

        # ── A2A bridge ────────────────────────────────────────────────────────
        bridge_status = {"running": False, "reason": "not attempted"}
        try:
            import json as _json
            _cfg = _json.loads((root / "config.json").read_text())
            if _cfg.get("a2a", {}).get("enabled", False):
                from a2a_bridge_daemon import ensure_bridge_running
                bridge_status = ensure_bridge_running(root, _cfg)
            else:
                bridge_status = {"running": False, "reason": "disabled in config"}
        except Exception as _e:
            bridge_status = {"running": False, "reason": str(_e)}

        if bridge_status.get("running"):
            bridge_line = (
                f"running (pid {bridge_status.get('pid')}, "
                f"{bridge_status.get('base_url')}, "
                f"v{bridge_status.get('version', '?')})"
            )
        else:
            bridge_line = f"not running — {bridge_status.get('reason', 'unknown')}"

        # ── Notification feed ─────────────────────────────────────────────────
        new_notifs: list = []
        update_msgs: list = []
        try:
            import json as _json
            _cfg = _json.loads((root / "config.json").read_text())
            new_notifs, update_msgs = _poll_notifications(root, _cfg)
        except Exception as _ne:
            logger.debug("Notification poll error (non-fatal): %s", _ne)

        # ── Self-inbox injection ──────────────────────────────────────────────
        self_notes = read_self_inbox(root)
        clear_self_inbox(root)

        # ── Monitor trigger injection ─────────────────────────────────────────
        monitor_triggers = []
        try:
            import json as _json
            triggers_file = root / "a2a" / "monitors" / "recent_triggers.json"
            if triggers_file.exists():
                monitor_triggers = _json.loads(triggers_file.read_text()) or []
                triggers_file.write_text("[]")
        except Exception:
            pass

        # Project banner: include the active isolation mode + legacy fallback
        # so users can see at a glance whether they're on per-repo or global
        # buckets and which legacy bucket the read-fallback chain still queries.
        try:
            _info = get_project_info(cwd)
            _branch = get_git_branch(cwd)
            _branch_str = f"  branch: {_branch}" if _branch else ""
            _project_line = (
                f"  • Project: {_info['project_id']}  ({_info['isolation_mode']}, "
                f"git={'yes' if _info['git_toplevel'] else 'no'}{_branch_str})  cwd: {cwd}\n"
                f"  • Legacy fallback: {LEGACY_GLOBAL_PROJECT_ID} "
                f"(read-only until backfill via scripts/repartition_by_repo.py)\n"
            )
        except Exception:
            _project_line = f"  • Project: {get_project_id(cwd)}  cwd: {cwd}\n"

        _recall_line = ""
        try:
            from shared.hook_metrics import read_last_recall_summary

            last = read_last_recall_summary(root)
            if last:
                sk = last.get("skip_reason") or ""
                _recall_line = (
                    f"  • Last recall: {last.get('recall_ms', '?')} ms; "
                    f"injected_chars={last.get('recall_injected_chars', '?')}/"
                    f"{last.get('recall_budget_chars', '?')}"
                    + (f"; skip={sk}" if sk else "")
                    + "\n"
                )
        except Exception:
            pass

        banner = (
            f"[AINL Graph Memory]  Plugin root: {root}\n"
            f"  • Graph DB: {db_s}\n"
            f"{_project_line}"
            f"{_recall_line}"
            f"  • Compression: {status['mode']} ({'on' if status['enabled'] else 'off'})  ~savings {status['savings']}\n"
            f"  • AINL Python tools module: {'yes' if ainl else 'no (optional)'}\n"
            f"  • ainl_native (Rust bindings): {native_status}\n"
            f"  • MCP stack (same venv as server): {'OK' if mcp_ok else 'FAIL – ' + mcp_detail}\n"
            f"  • venv on PATH (child processes): {venv_file_status}\n"
            f"  • A2A bridge: {bridge_line}\n"
            f"  • When Claude spawns MCP, expect ~{EXPECTED_MCP_TOOLS} tools (ainl + memory + a2a); "
            f"if missing, /plugin -> Installed -> ainl-cortex and /mcp, or /reload-plugins.\n"
        )

        system_blocks = [banner]

        # ── Sticky upgrade notice (Python backend — every session until migrated) ──
        if _backend == "python":
            _rust_installed = shutil.which("rustc") is not None
            if _rust_installed:
                _upgrade_how = (
                    "Rust is already installed — just ask me to re-run setup.sh to upgrade (no downloads needed)."
                )
            else:
                _upgrade_how = (
                    "Ask me to upgrade and I'll install Rust automatically and migrate your memory."
                )
            system_blocks.append(
                "\n━━━ AINL CORTEX: NATIVE BACKEND UPGRADE AVAILABLE ━━━\n"
                "Plugin is running on the Python backend. The native Rust backend adds:\n"
                "  • Trajectory distillation — learns patterns across sessions\n"
                "  • Procedure scoring — reuses your most successful workflows\n"
                "  • Anchored memory compression — preserves key context under pressure\n"
                f"{_upgrade_how}\n"
                "You should proactively mention this upgrade is available at the start of this session.\n"
                "━━━\n"
            )

        if self_notes:
            note_lines = ["\n━━━ SELF-NOTE FROM PRIOR SESSION ━━━"]
            for note in self_notes:
                import time as _t
                ts = _t.strftime("%Y-%m-%d %H:%M", _t.localtime(note.get("created_at", 0)))
                note_lines.append(f"[{ts}] {note.get('message', '')}")
                if note.get("context"):
                    note_lines.append(f"  Context: {note['context']}")
            note_lines.append("━━━ END SELF-NOTE ━━━\n")
            system_blocks.append("\n".join(note_lines))

        if monitor_triggers:
            trig_lines = ["\n━━━ PRE-SESSION MONITOR ALERTS ━━━"]
            for t in monitor_triggers:
                trig_lines.append(f"  • {t.get('message', str(t))}")
            trig_lines.append("━━━ END ALERTS ━━━\n")
            system_blocks.append("\n".join(trig_lines))

        # ── Pending improvement proposals ────────────────────────────────────
        try:
            from mcp_server.improvement_proposals import ImprovementProposalStore
            _prop_db = db_path.parent / "ainl_proposals.db"
            _pstore = ImprovementProposalStore(_prop_db)
            _pending = [p for p in _pstore.get_recent_proposals(limit=20)
                        if p.accepted is None and p.validation_passed]
            if _pending:
                system_blocks.append(
                    f"\n━━━ PENDING AINL IMPROVEMENT PROPOSALS ({len(_pending)}) ━━━\n"
                    + "\n".join(
                        f"  • [{p.improvement_type}] {p.rationale[:120]}  (id={p.id[:8]})"
                        for p in _pending[:5]
                    )
                    + ("\n  … and more — call ainl_list_proposals to see all" if len(_pending) > 5 else "")
                    + "\n  → Call ainl_accept_proposal(proposal_id, accepted=True/False) to review."
                    + "\n━━━ END PROPOSALS ━━━\n"
                )
        except Exception as _pe:
            logger.debug("Proposal surface error (non-fatal): %s", _pe)

        # ── Notification banner ───────────────────────────────────────────────
        notif_banner = _format_notif_banner(new_notifs, update_msgs)
        if notif_banner:
            system_blocks.append(notif_banner)

        # ── Compaction recovery brief (Python backend only) ───────────────────
        # Native backend has its own anchored summary (richer); only inject the
        # delta-based brief when Rust is not available.
        if not _NATIVE_OK:
            try:
                from shared.session_delta import build_compaction_brief
                _comp_brief = build_compaction_brief(root)
                if _comp_brief:
                    system_blocks.append(
                        "\n━━━ COMPACTION RECOVERY — RECENT SESSION WRITES ━━━\n"
                        + _comp_brief
                        + "\n━━━ END RECOVERY ━━━\n"
                    )
            except Exception as _cb_e:
                logger.debug("Compaction recovery brief failed (non-fatal): %s", _cb_e)

        # ── Autonomous tasks due ──────────────────────────────────────────────
        try:
            import json as _at_json
            _at_cfg = _at_json.loads((root / "config.json").read_text()).get("autonomous_mode", {})
            if _at_cfg.get("enabled", False) and _at_cfg.get("inject_due_tasks_in_startup", True):
                from graph_store import get_graph_store as _get_at_gs
                _at_project_id = get_project_id(cwd)
                _at_store = _get_at_gs(db_path)
                _lookahead_s = _at_cfg.get("due_tasks_lookahead_minutes", 60) * 60
                _all_active = _at_store.list_autonomous_tasks(
                    project_id=_at_project_id,
                    status='active',
                    due_only=False,
                )
                # Gap 1: separate approved-due from pending-approval
                _due_tasks = []
                _pending_approval = []
                for _t in _all_active:
                    import json as _psj
                    # Gap 3: path_scope filter — skip if cwd doesn't match any listed prefix
                    _scope_raw = _t.get('path_scope')
                    if _scope_raw:
                        try:
                            _scope_paths = _psj.loads(_scope_raw) if isinstance(_scope_raw, str) else _scope_raw
                            if not any(cwd.startswith(_sp) for _sp in _scope_paths):
                                continue
                        except Exception:
                            pass
                    _tier = _t.get('risk_tier', 'read_only')
                    _approved = _t.get('approved_by')
                    _nra = _t.get('next_run_at')
                    _is_due = _nra is not None and _nra <= time.time() + _lookahead_s
                    if _tier != 'read_only' and not _approved:
                        _pending_approval.append(_t)
                    elif _is_due:
                        _due_tasks.append(_t)
                if _due_tasks or _pending_approval:
                    def _fmt_due(ts):
                        if ts is None:
                            return "now"
                        delta = ts - time.time()
                        if delta <= 60:
                            return "OVERDUE" if delta < 0 else "now"
                        if delta < 3600:
                            return f"in {int(delta / 60)}m"
                        return f"in {int(delta / 3600)}h {int((delta % 3600) / 60)}m"

                    def _fmt_actions(raw):
                        import json as _aj
                        if raw is None:
                            return ""
                        try:
                            acts = _aj.loads(raw) if isinstance(raw, str) else raw
                            return f"  → authorized: {', '.join(acts)}" if acts else ""
                        except Exception:
                            return ""

                    if _due_tasks:
                        _sorted = sorted(
                            _due_tasks,
                            key=lambda x: (-x.get('priority', 5), x.get('next_run_at') or 0),
                        )[:10]
                        _task_lines = []
                        for t in _sorted:
                            _tier = t.get('risk_tier', 'read_only')
                            _line = (
                                f"  [{t.get('priority', 5):2d}] {t['description']}"
                                f"  [{t.get('trigger_type', 'scheduled')}|{_tier}]"
                                f"  {_fmt_due(t.get('next_run_at'))}"
                                f"  id={t['task_id']}"
                            )
                            _acts = _fmt_actions(t.get('allowed_actions'))
                            if _acts:
                                _line += f"\n{_acts}"
                            _task_lines.append(_line)
                        system_blocks.append(
                            "\n━━━ AUTONOMOUS TASKS DUE ━━━\n"
                            + "\n".join(_task_lines) + "\n\n"
                            + "Before executing each task call memory_begin_task_execution(task_id, project_id) "
                            "to activate the scope lock, then execute in priority order, "
                            "then call memory_complete_task(task_id=…, note=…).\n"
                            "━━━ END AUTONOMOUS TASKS ━━━\n"
                        )
                        logger.info("Injected %d autonomous task(s) due in startup", len(_due_tasks))

                    if _pending_approval:
                        _appr_lines = []
                        for t in _pending_approval[:5]:
                            _appr_lines.append(
                                f"  [{t.get('priority', 5):2d}] {t['description']}"
                                f"  [risk={t.get('risk_tier','?')}]"
                                f"  id={t['task_id']}"
                            )
                        system_blocks.append(
                            "\n━━━ TASKS AWAITING YOUR APPROVAL ━━━\n"
                            + "\n".join(_appr_lines) + "\n\n"
                            + "These tasks have risk_tier != 'read_only' and require explicit user approval "
                            "before they will fire. Present them to the user and call "
                            "memory_approve_task(task_id) if they consent.\n"
                            "━━━ END PENDING APPROVAL ━━━\n"
                        )
                        logger.info("Flagged %d task(s) awaiting approval", len(_pending_approval))
        except Exception as _at_e:
            logger.debug("Autonomous task injection failed (non-fatal): %s", _at_e)

        # ── Anchored summary + freshness gate (prior-session context) ─────────
        if _NATIVE_OK:
            try:
                _project_id = get_project_id(cwd)
                _native_db = str(Path.home() / ".claude" / "projects" / _project_id / "graph_memory" / "ainl_native.db")
                _ctx = _ainl_native.session_context(_native_db, _project_id)
                _raw = _ctx.get("summary_json")
                if _raw:
                    _s = json.loads(_raw)
                    _age_h = _ctx.get("age_hours", 0.0)
                    _age_str = f"{_age_h:.0f}h ago" if _age_h < 48 else f"{_age_h/24:.0f}d ago"
                    _freshness = _ctx.get("freshness", "Unknown")
                    _ok = _ctx.get("can_execute", True)
                    _lines = [f"\n━━━ PRIOR SESSION CONTEXT ({_age_str}) ━━━"]
                    _lines.append(f"  Summary: {_s.get('task_summary', '—')}")
                    _lines.append(f"  Outcome: {_s.get('outcome', '?')}  |  Captures: {_s.get('capture_count', 0)}")
                    if _s.get("tools_used"):
                        _lines.append(f"  Tools: {', '.join(_s['tools_used'][:8])}")
                    if _s.get("files_touched"):
                        _lines.append(f"  Files: {', '.join(_s['files_touched'][:6])}")
                    if _s.get("semantic_tags"):
                        _lines.append(f"  Tags: {', '.join(_s['semantic_tags'][:5])}")
                    _lines.append(f"  Context freshness: {_freshness} (execute: {'yes' if _ok else 'refresh recommended'})")
                    _lf = _s.get("last_finalize", {})
                    if _lf:
                        _lines.append(
                            f"  Persisted: {_lf.get('trajectory_steps', 0)} traj steps, "
                            f"{_lf.get('procedures_promoted', 0)} procedures promoted"
                        )
                    _lines.append("━━━ END PRIOR SESSION ━━━\n")
                    system_blocks.append("\n".join(_lines))
                    logger.info("Injected anchored summary from prior session")
            except Exception as _ae:
                logger.debug(f"Anchored summary load failed (non-fatal): {_ae}")

        # ── Environment snapshot reconciliation ───────────────────────────────
        # Compares current plugin root / name / backend against the last stored
        # snapshot and automatically flags stale references in graph memory.
        try:
            _recon_project_id = get_project_id(cwd)
            if _backend == "native" and _NATIVE_OK:
                _recon_db = str(db_path.parent / "ainl_native.db")
                _recon = _ainl_native.reconcile_environment(
                    _recon_db, _recon_project_id, str(root), _backend
                )
            else:
                from memory_reconcile import reconcile as _mem_reconcile
                from graph_store import get_graph_store as _get_gs
                _recon = _mem_reconcile(
                    _get_gs(db_path), _recon_project_id, str(root), _backend
                )
            if _recon.get("stale_found"):
                _recon_lines = ["\n⚡ MEMORY RECONCILIATION — stale references corrected:"]
                for _ch in _recon.get("changes", []):
                    _recon_lines.append(f"  • {_ch}")
                system_blocks.append("\n".join(_recon_lines))
                logger.info("Memory reconciliation: %s", _recon.get("changes"))
        except Exception as _re:
            logger.debug("Memory reconciliation failed (non-fatal): %s", _re)

        system_message = "\n".join(system_blocks)

        additional = (
            f"Session initialized with AINL graph memory. SQLite at {db_path}. "
            f"MCP preflight: {mcp_detail}. "
            f"A2A bridge: {'running' if bridge_status.get('running') else 'offline'}."
        )

        out = {
            "continue": True,
            "suppressOutput": False,
            "systemMessage": system_message,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": additional,
            },
        }

        try:
            from shared.hook_metrics import append_hook_metric

            append_hook_metric(
                root,
                "session_start",
                {"session_start_ms": round((time.perf_counter() - _ss_t0) * 1000, 2)},
            )
        except Exception:
            pass

        # Transcript: JSON stdout is what Claude documents; also mirror to stderr in raw terminals
        j = json.dumps(out)
        print(j, file=sys.stdout, flush=True)
        print(
            "AINL graph memory SessionStart: "
            f"db={db_path} mcp={'ok' if mcp_ok else 'fail'}",
            file=sys.stderr,
            flush=True,
        )

    except Exception as e:
        logger.error("SessionStart error: %s", e)
        out = {
            "continue": True,
            "suppressOutput": False,
            "systemMessage": f"[AINL Graph Memory] SessionStart error (non-fatal): {e}",
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": str(e),
            },
        }
        print(json.dumps(out), file=sys.stdout, flush=True)
    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()
