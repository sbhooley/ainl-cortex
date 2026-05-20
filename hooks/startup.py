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
from shared.project_id import get_project_id, get_project_info, LEGACY_GLOBAL_PROJECT_ID
from shared.a2a_inbox import read_self_inbox, clear_self_inbox
from notifications import poll as _poll_notifications, format_banner as _format_notif_banner
from session_banner import (
    build_main_banner,
    compression_status_from_config,
    format_prior_session_context,
)
from shared.session_delta import build_compaction_brief

try:
    import ainl_native as _ainl_native
    _NATIVE_OK = True
except ImportError:
    _ainl_native = None
    _NATIVE_OK = False

logger = get_logger("startup")

TOOL_COUNT_MEMORY = 22  # core + goals + tool outcome + session_history + 8 autonomous
TOOL_COUNT_AINL = 13
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
    """Backward-compatible wrapper; prefer compression_status_from_config()."""
    st = compression_status_from_config()
    return {
        "enabled": st.get("enabled", False),
        "mode": st.get("mode", "OFF"),
        "savings": st.get("mode", "OFF"),
        "line": st.get("line", "  • Compression: off\n"),
        "lines": st.get("lines", []),
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
    try:
        from mcp_server.platform_paths import venv_python

        return venv_python(plugin_root)
    except Exception:
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
    pycheck = (
        "from mcp_server.runtime_bootstrap import bootstrap_runtime; "
        "from mcp_server.import_compat import ("
        "verify_bare_node_types_import, verify_bare_graph_store_import, verify_bare_retrieval_import); "
        "bootstrap_runtime(heal_deps=True); "
        "import mcp.server; import mcp_server.graph_store; import mcp_server.server; "
        "assert verify_bare_node_types_import() and verify_bare_graph_store_import() "
        "and verify_bare_retrieval_import()"
    )
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


def _plugin_root_safe_for_env(plugin_root: Path) -> bool:
    """Refuse to persist ephemeral verify/tmp checkouts into session env."""
    try:
        resolved = plugin_root.resolve()
    except OSError:
        return False
    s = str(resolved).replace("\\", "/").lower()
    unsafe_markers = (
        "ainl-cortex-fresh",
        "/private/tmp/ainl-cortex",
        "/tmp/ainl-cortex",
        "/temp/ainl-cortex",
        "\\temp\\ainl-cortex",
    )
    if any(m in s for m in unsafe_markers):
        return False
    return resolved.is_dir() and (resolved / "hooks" / "startup.py").is_file()


def append_venv_to_envfile(plugin_root: Path) -> str:
    fe = os.environ.get("CLAUDE_ENV_FILE")
    if not fe:
        return "CLAUDE_ENV_FILE not set (optional)"
    if not _plugin_root_safe_for_env(plugin_root):
        return f"skipped unsafe plugin_root for CLAUDE_ENV_FILE: {plugin_root}"
    try:
        from mcp_server.platform_paths import is_windows, pythonpath_for_plugin, venv_bin_dir

        bindir = venv_bin_dir(plugin_root)
        py_path = pythonpath_for_plugin(plugin_root)
        sep = os.pathsep
        if is_windows():
            bindir_s = bindir.as_posix()
            line = (
                f'\n# ainl-cortex (SessionStart)\n'
                f'export PATH="{bindir_s}{sep}$PATH"\n'
                f'export PYTHONPATH="{py_path}{sep}$PYTHONPATH"\n'
            )
        else:
            line = (
                f'\n# ainl-cortex (SessionStart)\n'
                f'export PATH="{bindir}{sep}$PATH"\n'
                f'export PYTHONPATH="{py_path}{sep}$PYTHONPATH"\n'
            )
        with open(fe, "a", encoding="utf-8") as f:
            f.write(line)
        return f"appended to {fe}"
    except OSError as e:
        return f"could not write CLAUDE_ENV_FILE: {e}"


def _ainl_native_installed_so() -> Optional[Path]:
    """Return path to the compiled extension module, if importable."""
    try:
        import importlib.util

        spec = importlib.util.find_spec("ainl_native")
        if spec is None or not spec.origin:
            return None
        pkg = Path(spec.origin).resolve().parent
        for name in ("ainl_native.abi3.so", "ainl_native.so", "ainl_native.pyd"):
            candidate = pkg / name
            if candidate.is_file():
                return candidate
    except Exception:
        return None
    return None


def _ainl_native_sources_stale(plugin_root: Path, installed_so: Path) -> bool:
    """True when Rust sources are newer than the installed extension binary."""
    native_dir = plugin_root / "ainl_native"
    try:
        built_mtime = installed_so.stat().st_mtime
    except OSError:
        return True
    watch = [native_dir / "Cargo.toml", native_dir / "Cargo.lock"]
    watch.extend((native_dir / "src").glob("**/*.rs"))
    for path in watch:
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime > built_mtime:
                return True
        except OSError:
            continue
    return False


_AINL_NATIVE_PYPI_MIN = "0.1.1"


def _pip_install_ainl_native(py: Path) -> Optional[str]:
    """Install prebuilt wheel from PyPI when available for this platform."""
    if os.environ.get("AINL_NATIVE_BUILD_FROM_SOURCE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return None
    try:
        r = subprocess.run(
            [
                str(py),
                "-m",
                "pip",
                "install",
                f"ainl_native>={_AINL_NATIVE_PYPI_MIN}",
                "--upgrade",
                "--quiet",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if r.returncode == 0:
            return "installed from PyPI"
    except Exception:
        pass
    return None


def _run_maturin_develop(plugin_root: Path, native_dir: Path, py: Path) -> str:
    maturin = plugin_root / ".venv" / "bin" / "maturin"
    if not maturin.is_file():
        try:
            subprocess.run(
                [str(py), "-m", "pip", "install", "maturin", "--quiet"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
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
        err = (r.stderr or r.stdout or "").strip()[-200:]
        return f"build failed: {err}"
    except subprocess.TimeoutExpired:
        return "build timed out (>5 min)"
    except Exception as e:
        return f"build error: {e}"


def _ensure_ainl_native(plugin_root: Path) -> str:
    """
    Ensure ainl_native Rust extension is built and installed.
    Rebuilds when Rust sources are newer than the installed .so (git pull / plugin update).
    Returns a short status string for the banner.
    """
    native_dir = plugin_root / "ainl_native"
    if not native_dir.is_dir():
        return "skipped (ainl_native/ directory not found)"

    py = _venv_python(plugin_root)
    if py is None:
        return "skipped (no venv python)"

    installed_so = _ainl_native_installed_so()
    if installed_so is not None and not _ainl_native_sources_stale(plugin_root, installed_so):
        return "ok (already installed)"

    pip_note = _pip_install_ainl_native(py)
    installed_so = _ainl_native_installed_so()
    if installed_so is not None and not _ainl_native_sources_stale(plugin_root, installed_so):
        return f"ok ({pip_note})" if pip_note else "ok (already installed)"

    if installed_so is not None:
        status = _run_maturin_develop(plugin_root, native_dir, py)
        if status == "built + installed":
            suffix = f"; PyPI: {pip_note}" if pip_note else ""
            return f"rebuilt (sources newer than extension){suffix}"
        return status

    status = _run_maturin_develop(plugin_root, native_dir, py)
    if status != "built + installed" and pip_note:
        return f"{status} (PyPI attempt: {pip_note})"
    return status


def _clear_stale_scope_lock(plugin_root: Path) -> None:
    """Remove orphaned active_task.json from a crashed prior session."""
    try:
        sidecar = Path(plugin_root) / "logs" / "active_task.json"
        if sidecar.is_file():
            sidecar.unlink()
    except Exception as exc:
        logger.debug("clear stale scope lock failed (non-fatal): %s", exc)


def _task_allowed_for_cwd(task: dict, cwd: str) -> bool:
    """path_scope must match cwd as a path prefix (not raw string prefix)."""
    raw = task.get("path_scope")
    if not raw:
        return True
    if isinstance(raw, str):
        try:
            scopes = json.loads(raw)
        except json.JSONDecodeError:
            scopes = [raw]
    else:
        scopes = raw
    if not scopes:
        return True
    cwd_s = str(cwd)
    for base in scopes:
        base_s = str(base).rstrip("/")
        if cwd_s == base_s or cwd_s.startswith(base_s + "/"):
            return True
    return False


def _cwd_matches_path_scope(cwd: str, scopes: list) -> bool:
    """Used by startup injection; path prefix match avoids false string-prefix matches."""
    cwd_s = str(cwd)
    for base in scopes:
        base_s = str(base).rstrip("/")
        if cwd_s == base_s or cwd_s.startswith(base_s + "/"):
            return True
    return False


def _inject_autonomous_blocks(
    blocks: list,
    store,
    project_id: str,
    cwd: str,
    at_cfg: dict,
) -> None:
    """Append due / pending-approval autonomous task sections (non-fatal)."""
    if not at_cfg.get("enabled", True):
        return
    if not at_cfg.get("inject_due_tasks_in_startup", True):
        return

    lookahead_min = float(at_cfg.get("due_tasks_lookahead_minutes", 60) or 60)
    due_before = time.time() + lookahead_min * 60
    candidates = store.list_autonomous_tasks(
        project_id,
        status="active",
        due_only=True,
        due_before=due_before,
        limit=50,
    )

    due_lines: list[str] = []
    pending_approval: list[str] = []

    for task in candidates:
        raw_scope = task.get("path_scope")
        if raw_scope:
            if isinstance(raw_scope, str):
                try:
                    scopes = json.loads(raw_scope)
                except json.JSONDecodeError:
                    scopes = [raw_scope]
            else:
                scopes = raw_scope
            scope_ok = False
            for base in scopes:
                base_s = str(base).rstrip("/")
                if cwd == base_s or cwd.startswith(base_s + "/"):
                    scope_ok = True
                    break
            if not scope_ok:
                continue
        tier = task.get("risk_tier") or "read_only"
        approved = task.get("approved_by")
        desc = task.get("description", "")
        tid = task.get("task_id", "")
        if tier != "read_only" and not approved:
            pending_approval.append(f"  • [{tier}] {desc} (id={tid})")
            continue
        due_lines.append(f"  • (p{task.get('priority', 5)}) {desc} (id={tid})")
        if task.get("allowed_actions"):
            aa = task.get("allowed_actions")
            if isinstance(aa, str):
                try:
                    aa = json.loads(aa)
                except json.JSONDecodeError:
                    aa = [aa]
            due_lines.append(f"    allowed_actions: {aa}")

    if due_lines:
        blocks.append(
            "\n━━━ AUTONOMOUS TASKS DUE ━━━\n"
            + "\n".join(due_lines)
            + "\n  → Run memory_begin_task_execution then memory_complete_task when done.\n"
            + "━━━ END AUTONOMOUS TASKS DUE ━━━\n"
        )

    if pending_approval:
        blocks.append(
            "\n━━━ TASKS AWAITING YOUR APPROVAL ━━━\n"
            + "\n".join(pending_approval)
            + "\n  → Approve with memory_approve_task before execution.\n"
            + "━━━ END APPROVAL ━━━\n"
        )


def main():
    try:
        _ss_t0 = time.perf_counter()
        root = _plugin_root()
        _clear_stale_scope_lock(root)
        cwd = _hook_cwd()
        logger.info("SessionStart: plugin=%s cwd=%s", root, cwd)

        status = get_compression_status()
        ainl = check_ainl_tools()
        db_path = get_db_path(cwd)
        try:
            db_s = warm_database(db_path)
        except OSError as e:
            db_s = f"error: {e}"

        mcp_ok, mcp_detail = verify_mcp_imports(root)
        _ainl_heal_msg = ""
        # Self-heal ainativelang in venv (idempotent; safe on python-only backend)
        try:
            sys.path.insert(0, str(root))
            from mcp_server.deps_compat import ensure_ainativelang, ainativelang_importable
            _ainl_heal_ok, _ainl_heal_msg = ensure_ainativelang(root)
            ainl = ainativelang_importable()
        except Exception as _ae:
            _ainl_heal_ok, _ainl_heal_msg = False, str(_ae)
        _session_extras = {}
        try:
            sys.path.insert(0, str(root))
            from mcp_server.runtime_bootstrap import session_start_extras
            _session_extras = session_start_extras(root)
        except Exception:
            pass
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
                        native_status += " — unmigrated data detected (auto-migrate will run on SessionStart when store_backend=native)"
            except Exception:
                pass
        else:
            native_status = "skipped (python backend selected)"
        venv_file_status = append_venv_to_envfile(root)
        logger.debug("venv PATH hook: %s", venv_file_status)

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
            logger.debug(
                "A2A bridge running pid=%s url=%s",
                bridge_status.get("pid"),
                bridge_status.get("base_url"),
            )
        else:
            logger.debug("A2A bridge offline: %s", bridge_status.get("reason", "unknown"))

        if bridge_status.get("running"):
            _bridge_line = (
                f"running (pid {bridge_status.get('pid')}, "
                f"{bridge_status.get('base_url')}, "
                f"v{bridge_status.get('version', '?')})"
            )
        else:
            _bridge_line = f"not running — {bridge_status.get('reason', 'unknown')}"

        if bridge_status.get("running") and bridge_status.get("base_url"):
            try:
                from shared.armaraos_daemon import fetch_daemon_cost_hint

                _eco = fetch_daemon_cost_hint(str(bridge_status["base_url"]))
                if _eco and _eco.get("tokens_saved"):
                    _bridge_line += f" · ArmaraOS eco ↓~{_eco['tokens_saved']} tok"
            except Exception:
                pass

        # ── Project doc sync (AGENTS.md / CLAUDE.md) ─────────────────────────
        try:
            sys.path.insert(0, str(root / "mcp_server"))
            from graph_store import get_graph_store
            from project_context_sync import sync_project_docs

            _pcs_pid = get_project_id(cwd)
            _gm = Path.home() / ".claude" / "projects" / _pcs_pid / "graph_memory"
            _dbp = _gm / "ainl_memory.db"
            if _dbp.exists() or (_gm / "ainl_native.db").exists():
                _store = get_graph_store(_dbp)
                sync_project_docs(_store, _pcs_pid, cwd)
        except Exception as _pcs:
            logger.debug("project_context_sync failed (non-fatal): %s", _pcs)

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

        _a2a_enabled = False
        try:
            import json as _json
            _cfg_early = _json.loads((root / "config.json").read_text())
            _a2a_enabled = bool(_cfg_early.get("a2a", {}).get("enabled", False))
        except Exception:
            pass

        _project_id = get_project_id(cwd)
        _isolation_mode = "per_repo"
        _git_repo = False
        try:
            _info = get_project_info(cwd)
            _project_id = _info["project_id"]
            _isolation_mode = _info.get("isolation_mode", "per_repo")
            _git_repo = bool(_info.get("git_toplevel"))
        except Exception:
            pass

        try:
            _inbox = root / "inbox"
            _inbox.mkdir(parents=True, exist_ok=True)
            (_inbox / "current_project_id.txt").write_text(str(_project_id), encoding="utf-8")
        except Exception as _cp_e:
            logger.debug("current_project_id sidecar failed (non-fatal): %s", _cp_e)

        _cost_line = ""
        try:
            from shared.hook_metrics import format_cost_banner_line

            _cost_line = format_cost_banner_line(root)
            if _cost_line:
                _cost_line = f"  • {_cost_line}"
        except Exception:
            pass

        _recall_line = ""
        try:
            from shared.hook_metrics import read_last_recall_summary

            last = read_last_recall_summary(root)
            if last:
                sk = last.get("skip_reason") or ""
                _recall_line = (
                    f"  • Last recall: {last.get('recall_ms', '?')} ms; "
                    f"injected {last.get('recall_injected_chars', '?')}/"
                    f"{last.get('recall_budget_chars', '?')} chars"
                    + (f" (skip: {sk})" if sk else "")
                )
        except Exception:
            pass

        banner = build_main_banner(
            root=root,
            backend=_backend,
            db_s=db_s,
            project_id=_project_id,
            isolation_mode=_isolation_mode,
            git_repo=_git_repo,
            cwd=cwd,
            legacy_project_id=LEGACY_GLOBAL_PROJECT_ID,
            compression_lines=status.get("lines"),
            compression_line=status.get("line", "  • Compression: off\n"),
            ainl_ok=ainl,
            ainl_heal_msg=_ainl_heal_msg,
            mcp_ok=mcp_ok,
            mcp_detail=mcp_detail,
            native_status=native_status,
            venv_file_status=venv_file_status,
            expected_tools=EXPECTED_MCP_TOOLS,
            bridge_line=_bridge_line,
            recall_line=_recall_line,
            cost_line=_cost_line,
        )

        system_blocks = [banner]

        _op_banner = _session_extras.get("operator_banner") or ""
        if _op_banner:
            system_blocks.append(_op_banner.rstrip("\n") + "\n")
        _upgrade_banner = _session_extras.get("upgrade_runbook_banner") or ""
        if _upgrade_banner:
            system_blocks.append(_upgrade_banner.rstrip("\n") + "\n")
        if _session_extras.get("stale_mcp") and _session_extras.get("stale_mcp_message"):
            system_blocks.append(
                "  • " + _session_extras["stale_mcp_message"].replace("\n", " ") + "\n"
            )
        if _session_extras.get("auto_migrate_ran"):
            system_blocks.append(
                f"  • Native migration: {_session_extras.get('auto_migrate_message', 'completed')} "
                "— run /reload-plugins.\n"
            )

        # Full upgrade runbook is in upgrade_runbook_banner (see native_upgrade_runbook.format_banner).

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
                    system_blocks.append(
                        format_prior_session_context(
                            _s,
                            age_str=_age_str,
                            freshness=_freshness,
                            can_execute=_ok,
                        )
                    )
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

        if not _NATIVE_OK:
            try:
                _recovery_brief = build_compaction_brief(root)
                if _recovery_brief.strip():
                    system_blocks.append(
                        "\n━━━ COMPACTION RECOVERY ━━━\n"
                        + _recovery_brief
                        + "\n━━━ END RECOVERY ━━━\n"
                    )
                    logger.info("Injected compaction recovery brief")
            except Exception as _cr:
                logger.debug("Compaction recovery brief failed (non-fatal): %s", _cr)

        # ── Autonomous task injection (due + pending approval) ───────────────
        try:
            import json as _json
            _at_cfg = _json.loads((root / "config.json").read_text()).get(
                "autonomous_mode", {}
            )
            if _at_cfg.get("enabled", True):
                sys.path.insert(0, str(root))
                from mcp_server.graph_store import get_graph_store as _get_gs_at

                _at_store = _get_gs_at(db_path)
                _inject_autonomous_blocks(
                    system_blocks,
                    _at_store,
                    _project_id,
                    str(cwd),
                    _at_cfg,
                )
        except Exception as _at_e:
            logger.debug("Autonomous task injection failed (non-fatal): %s", _at_e)

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
