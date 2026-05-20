"""
Cross-platform paths for venv, hooks, and MCP launch.

Used by setup, mcp_launch.py, run_hook.py, and runtime self-heal checks.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

MANIFEST_NAME = "install_manifest.json"


def os_family() -> str:
    """``windows`` | ``darwin`` | ``linux`` | ``other``."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    return "other"


def is_windows() -> bool:
    return os_family() == "windows"


def plugin_root(explicit: Optional[Path] = None) -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if explicit is not None:
        return explicit.resolve()
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def is_cache_plugin_path(path: Path) -> bool:
    return "/plugins/cache/" in str(path.resolve()).replace("\\", "/")


def is_valid_plugin_root(path: Path) -> bool:
    root = path.resolve()
    return (root / "hooks" / "startup.py").is_file()


def standard_plugin_path() -> Path:
    """Recommended live git install (not Claude marketplace cache)."""
    return Path.home() / ".claude" / "plugins" / "ainl-cortex"


def plugin_version(path: Path) -> str:
    """Semver string from ``.claude-plugin/plugin.json`` (empty if missing)."""
    manifest = path / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        return ""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return str(data.get("version") or "").strip()
    except (json.JSONDecodeError, OSError):
        return ""


def _plugin_version_tuple(path: Path) -> tuple:
    manifest = path / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        return (0, 0, 0)
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        ver = str(data.get("version") or "0.0.0").strip()
        parts = []
        for piece in ver.split("."):
            try:
                parts.append(int(piece))
            except ValueError:
                parts.append(0)
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])
    except (json.JSONDecodeError, OSError):
        return (0, 0, 0)


def canonical_plugin_root(current: Optional[Path] = None) -> Path:
    """
    Prefer a live git/marketplace-link install over a stale Claude cache copy.

    When ``installed_plugins.json`` still points at ``plugins/cache/…`` but the
    user cloned to ``~/.claude/plugins/ainl-cortex``, self-heal must register
    the live tree — not re-sync back to the old cache path.
    """
    current = (current or plugin_root()).resolve()
    candidates: List[Path] = []

    standard = standard_plugin_path()
    if standard.is_dir():
        candidates.append(standard.resolve())

    mp_link = Path.home() / ".claude" / "ainl-local-marketplace" / "plugins" / "ainl-cortex"
    if mp_link.exists():
        candidates.append(mp_link.resolve())

    candidates.append(current)

    valid: List[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if is_valid_plugin_root(candidate):
            valid.append(candidate)

    if not valid:
        return current

    non_cache = [p for p in valid if not is_cache_plugin_path(p)]
    pool = non_cache or valid
    return max(pool, key=lambda p: (_plugin_version_tuple(p), len(str(p))))


def venv_bin_dir(root: Optional[Path] = None) -> Path:
    root = root or plugin_root()
    if is_windows():
        return root / ".venv" / "Scripts"
    return root / ".venv" / "bin"


def venv_lib_dir(root: Optional[Path] = None) -> Path:
    return (root or plugin_root()) / ".venv" / "lib"


def _python_names() -> List[str]:
    if is_windows():
        return ["python.exe", "python3.exe", "python"]
    return ["python3", "python3.14", "python3.13", "python3.12", "python3.11", "python"]


def venv_python(root: Optional[Path] = None) -> Optional[Path]:
    """Resolved venv interpreter, or None if missing."""
    bindir = venv_bin_dir(root)
    for name in _python_names():
        p = bindir / name
        if p.is_file():
            return p.resolve()
    return None


def venv_pip(root: Optional[Path] = None) -> Optional[Path]:
    bindir = venv_bin_dir(root)
    for name in ("pip.exe", "pip3.exe", "pip", "pip3") if is_windows() else ("pip", "pip3"):
        p = bindir / name
        if p.is_file():
            return p.resolve()
    return None


def venv_site_packages(root: Optional[Path] = None) -> Optional[Path]:
    root = root or plugin_root()
    lib = venv_lib_dir(root)
    if not lib.is_dir():
        return None
    for d in sorted(lib.glob("python*")):
        site = d / "site-packages"
        if site.is_dir():
            return site.resolve()
    return None


def pythonpath_for_plugin(root: Optional[Path] = None) -> str:
    """``PYTHONPATH`` value for hooks and MCP (OS-specific separator)."""
    root = root or plugin_root()
    parts = [str(root), str(root / "mcp_server")]
    site = venv_site_packages(root)
    if site:
        parts.append(str(site))
    return os.pathsep.join(parts)


def manifest_path(root: Optional[Path] = None) -> Path:
    return (root or plugin_root()) / MANIFEST_NAME


def read_install_manifest(root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    path = manifest_path(root)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_install_manifest(root: Optional[Path] = None, **extra: Any) -> Dict[str, Any]:
    root = root or plugin_root()
    vpy = venv_python(root)
    payload: Dict[str, Any] = {
        "platform": os_family(),
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "platform_machine": platform.machine(),
        "python_version": platform.python_version(),
        "venv_python": str(vpy) if vpy else None,
        "venv_pip": str(venv_pip(root) or ""),
        "installed_at": time.time(),
    }
    payload.update(extra)
    manifest_path(root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def find_system_python() -> Optional[Path]:
    """Best-effort system Python for bootstrapping venv before it exists."""
    import shutil

    candidates = ["python3", "python", "py"]
    if is_windows():
        candidates = ["python", "py", "python3"]
    for name in candidates:
        w = shutil.which(name)
        if w:
            return Path(w).resolve()
    if is_windows():
        for base in (
            os.environ.get("LOCALAPPDATA", ""),
            os.environ.get("ProgramFiles", ""),
        ):
            if not base:
                continue
            for sub in (
                "Programs/Python/Python314/python.exe",
                "Programs/Python/Python313/python.exe",
                "Programs/Python/Python312/python.exe",
                "Programs/Python/Python311/python.exe",
            ):
                p = Path(base) / sub
                if p.is_file():
                    return p.resolve()
    return None


def hook_python_invocation() -> str:
    """Interpreter token(s) for hooks.json / plugin MCP (bootstrap only)."""
    if is_windows():
        return "py -3"
    return "python3"


def hook_command(hook_script: str, root: Optional[Path] = None) -> str:
    """
    Portable hooks.json command (macOS, Linux, Windows).

    Windows uses ``run_hook.cmd`` so hooks work before Python is on PATH (uv bootstrap).
    """
    _ = root
    if is_windows():
        return (
            f'"${{CLAUDE_PLUGIN_ROOT}}/scripts/run_hook.cmd" {hook_script}'
        )
    py = hook_python_invocation()
    return f'{py} "${{CLAUDE_PLUGIN_ROOT}}/scripts/run_hook.py" {hook_script}'
