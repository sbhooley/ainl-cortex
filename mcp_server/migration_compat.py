"""Auto-migrate Python graph memory to native when configured and data is unmigrated."""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .import_compat import plugin_root, venv_python
from .native_compat import ainl_native_importable, ensure_ainl_native, read_store_backend

logger = logging.getLogger(__name__)

_STATE_FILE = "auto_migrate_state.json"
_MIN_PY_DB_BYTES = 8192
_COOLDOWN_SEC = 24 * 3600


def _logs_dir(root: Path) -> Path:
    d = root / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_config(root: Path) -> Dict[str, Any]:
    try:
        return json.loads((root / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def auto_migrate_enabled(root: Optional[Path] = None) -> bool:
    root = root or plugin_root()
    cfg = _read_config(root)
    mem = cfg.get("memory", {})
    if mem.get("auto_migrate_to_native") is False:
        return False
    # Default on when native backend selected
    return read_store_backend(root) == "native"


def native_db_empty(native_db: Path) -> bool:
    if not native_db.exists():
        return True
    if native_db.stat().st_size < 512:
        return True
    try:
        conn = sqlite3.connect(str(native_db))
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
            return n == 0
        finally:
            conn.close()
    except sqlite3.Error:
        return True


def python_db_has_data(py_db: Path) -> bool:
    if not py_db.is_file() or py_db.stat().st_size < _MIN_PY_DB_BYTES:
        return False
    try:
        conn = sqlite3.connect(str(py_db))
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM ainl_graph_nodes"
            ).fetchone()
            return bool(row and row[0] > 0)
        except sqlite3.Error:
            return py_db.stat().st_size >= _MIN_PY_DB_BYTES
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def needs_native_migration(root: Path, py_db: Path) -> bool:
    native_db = py_db.parent / "ainl_native.db"
    return python_db_has_data(py_db) and native_db_empty(native_db)


def _load_state(root: Path) -> Dict[str, Any]:
    path = _logs_dir(root) / _STATE_FILE
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(root: Path, state: Dict[str, Any]) -> None:
    try:
        (_logs_dir(root) / _STATE_FILE).write_text(
            json.dumps(state, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _cooldown_active(root: Path) -> bool:
    state = _load_state(root)
    last = state.get("last_attempt_at")
    if not isinstance(last, (int, float)):
        return False
    return (time.time() - last) < _COOLDOWN_SEC


def maybe_auto_migrate(
    root: Optional[Path] = None,
    py_db: Optional[Path] = None,
    *,
    force: bool = False,
) -> Tuple[bool, str]:
    """
    Run ``scripts/migrate_python_to_native.sh`` when native is configured,
    ainl_native is available, python DB has data, and native DB is empty.

    Returns (ran_or_ok, status_message). Never raises.
    """
    root = root or plugin_root()
    if not auto_migrate_enabled(root):
        return False, "auto_migrate disabled or store_backend is python"

    if not force and _cooldown_active(root):
        return False, "auto_migrate cooldown (24h)"

    if py_db is None:
        return False, "no db path"

    if not needs_native_migration(root, py_db):
        return False, "no unmigrated python data for this project"

    ok, nat_msg = ensure_ainl_native(root)
    if not ok and not ainl_native_importable():
        return False, f"ainl_native unavailable: {nat_msg}"

    py = venv_python(root)
    if py is None:
        return False, "no venv python"

    script = root / "scripts" / "migrate_python_to_native.sh"
    if not script.is_file():
        return False, "migrate script missing"

    _save_state(root, {"last_attempt_at": time.time(), "py_db": str(py_db)})

    try:
        r = subprocess.run(
            ["bash", str(script)],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        out = (r.stdout or "")[-400:]
        err = (r.stderr or "")[-400:]
        if r.returncode == 0:
            logger.info("Auto-migration to native completed for %s", py_db.parent)
            _save_state(
                root,
                {
                    "last_attempt_at": time.time(),
                    "last_success_at": time.time(),
                    "py_db": str(py_db),
                },
            )
            return True, "auto-migrated python → native (see logs/migration_*.json)"
        msg = f"migration failed (exit {r.returncode}): {(err or out).strip()[:200]}"
        logger.warning(msg)
        _save_state(root, {"last_attempt_at": time.time(), "last_error": msg, "py_db": str(py_db)})
        return False, msg
    except subprocess.TimeoutExpired:
        return False, "migration timed out (>10 min)"
    except Exception as exc:
        return False, str(exc)


def scan_and_auto_migrate_all_projects(root: Optional[Path] = None) -> Tuple[bool, str]:
    """Scan ~/.claude/projects for unmigrated graph_memory dirs."""
    root = root or plugin_root()
    if not auto_migrate_enabled(root):
        return False, "auto_migrate disabled"

    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return False, "no projects dir"

    migrated_any = False
    messages = []
    for proj in sorted(base.iterdir()):
        gm = proj / "graph_memory"
        py_db = gm / "ainl_memory.db"
        if not py_db.is_file():
            continue
        if not needs_native_migration(root, py_db):
            continue
        ok, msg = maybe_auto_migrate(root, py_db)
        messages.append(f"{proj.name}: {msg}")
        if ok:
            migrated_any = True
            break  # one project per session start to avoid long blocking

    if migrated_any:
        return True, "; ".join(messages)
    if messages:
        return False, "; ".join(messages)
    return False, "no unmigrated projects"
