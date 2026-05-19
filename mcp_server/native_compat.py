"""Native store backend self-heal: ainl_native wheel + honest python fallback."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from .import_compat import plugin_root, venv_python

logger = logging.getLogger(__name__)

_AINL_NATIVE_MIN = "0.1.1"
_native_install_attempted = False


def ainl_native_importable() -> bool:
    try:
        import ainl_native  # noqa: F401
        return True
    except ImportError:
        return False


def read_store_backend(root: Optional[Path] = None) -> str:
    root = root or plugin_root()
    try:
        cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
        return str(cfg.get("memory", {}).get("store_backend", "python"))
    except Exception:
        return "python"


def sync_store_backend_to_python(root: Optional[Path] = None, *, reason: str = "") -> bool:
    """Write config.json store_backend to python when native cannot run."""
    root = root or plugin_root()
    cfg_path = root / "config.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("sync_store_backend_to_python: cannot read config: %s", exc)
        return False
    mem = cfg.setdefault("memory", {})
    if mem.get("store_backend") != "native":
        return False
    mem["store_backend"] = "python"
    mem["store_backend_fallback_reason"] = reason[:500]
    mem["store_backend_fallback_at"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
    try:
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        log_dir = root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "native_fallback.json").write_text(
            json.dumps({"reason": reason}, indent=2),
            encoding="utf-8",
        )
        logger.warning("Auto-set store_backend to python (%s)", reason[:120])
        return True
    except OSError as exc:
        logger.warning("sync_store_backend_to_python write failed: %s", exc)
        return False


def ensure_ainl_native(root: Optional[Path] = None, *, force: bool = False) -> Tuple[bool, str]:
    """PyPI wheel install for ainl_native (same policy as hooks/startup)."""
    global _native_install_attempted
    root = root or plugin_root()
    if ainl_native_importable() and not force:
        return True, "ainl_native already importable"

    if __import__("os").environ.get("AINL_NATIVE_BUILD_FROM_SOURCE", "").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        return False, "AINL_NATIVE_BUILD_FROM_SOURCE set"

    py = venv_python(root)
    if py is None:
        return False, "no venv python"

    if _native_install_attempted and not force:
        if ainl_native_importable():
            return True, "ainl_native importable"
        return False, "ainl_native install already attempted"

    _native_install_attempted = True
    try:
        r = subprocess.run(
            [
                str(py),
                "-m",
                "pip",
                "install",
                f"ainl_native>={_AINL_NATIVE_MIN}",
                "--upgrade",
                "--quiet",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if r.returncode == 0 and ainl_native_importable():
            logger.info("Auto-installed ainl_native from PyPI")
            return True, "installed ainl_native from PyPI"
        err = (r.stderr or r.stdout or "").strip()[:200]
        return False, f"ainl_native pip failed: {err}"
    except Exception as exc:
        return False, str(exc)


def heal_native_backend_failure(root: Optional[Path] = None, exc: Optional[BaseException] = None) -> bool:
    """Try pip install; on failure persist python backend in config."""
    root = root or plugin_root()
    if read_store_backend(root) != "native":
        return False
    ok, msg = ensure_ainl_native(root, force=True)
    if ok:
        return True
    reason = f"native backend unavailable: {msg}"
    if exc is not None:
        reason = f"{reason}; {exc}"
    return sync_store_backend_to_python(root, reason=reason)
