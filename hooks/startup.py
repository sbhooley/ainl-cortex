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
from pathlib import Path
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
_mcp_dir = str(Path(__file__).resolve().parent.parent / "mcp_server")
if _mcp_dir not in sys.path:
    sys.path.insert(0, _mcp_dir)

from shared.logger import get_logger
from shared.project_id import get_project_id

logger = get_logger("startup")

TOOL_COUNT_MEMORY = 7
TOOL_COUNT_AINL = 6
EXPECTED_MCP_TOOLS = TOOL_COUNT_MEMORY + TOOL_COUNT_AINL


def _plugin_root() -> Path:
    p = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if p:
        return Path(p).resolve()
    return Path(__file__).resolve().parent.parent


def _hook_cwd() -> Path:
    try:
        if not sys.stdin.isatty():
            data = json.load(sys.stdin)
            c = data.get("cwd")
            if c:
                return Path(c)
    except (json.JSONDecodeError, OSError, TypeError, AttributeError):
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
        line = f'\n# ainl-graph-memory (SessionStart)\nexport PATH="{plugin_root / ".venv" / "bin"}:$PATH"\n'
        line += f'export PYTHONPATH="{plugin_root}:$PYTHONPATH"\n'
        with open(fe, "a", encoding="utf-8") as f:
            f.write(line)
        return f"appended to {fe}"
    except OSError as e:
        return f"could not write CLAUDE_ENV_FILE: {e}"


def main():
    try:
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

        mcp_ok, mcp_detail = verify_mcp_imports(root)
        venv_file_status = append_venv_to_envfile(root)

        banner = (
            f"[AINL Graph Memory]  Plugin root: {root}\n"
            f"  • Graph DB: {db_s}\n"
            f"  • Project: {get_project_id(cwd)}  cwd: {cwd}\n"
            f"  • Compression: {status['mode']} ({'on' if status['enabled'] else 'off'})  ~savings {status['savings']}\n"
            f"  • AINL Python tools module: {'yes' if ainl else 'no (optional)'}\n"
            f"  • MCP stack (same venv as server): {'OK' if mcp_ok else 'FAIL – ' + mcp_detail}\n"
            f"  • venv on PATH (child processes): {venv_file_status}\n"
            f"  • When Claude spawns MCP, expect ~{EXPECTED_MCP_TOOLS} tools (ainl + memory); "
            f"if missing, /plugin -> Installed -> ainl-graph-memory and /mcp, or /reload-plugins.\n"
        )

        additional = (
            f"Session initialized with AINL graph memory. SQLite at {db_path}. "
            f"MCP preflight: {mcp_detail}."
        )

        out = {
            "continue": True,
            "suppressOutput": False,
            "systemMessage": banner,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": additional,
            },
        }

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
