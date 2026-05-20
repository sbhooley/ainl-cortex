"""Refresh plugin source on disk (Windows cache installs + git pull).

Claude Code marketplace installs often load ``plugins/cache/ainl-local/…/<version>``.
``/reload-plugins`` reuses that frozen copy — unlike a live ``git clone`` on macOS.
This module pulls the canonical tree and repoints ``installed_plugins.json``.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

from .platform_paths import (
    canonical_plugin_root,
    is_cache_plugin_path,
    is_valid_plugin_root,
    plugin_version,
    standard_plugin_path,
)

logger = logging.getLogger(__name__)

REPO_URL = "https://github.com/sbhooley/ainl-cortex.git"
_PULL_COOLDOWN_SEC = 300.0


def _pull_stamp_path(root: Path) -> Path:
    return root / "logs" / "last_git_pull.json"


def is_git_repo(root: Path) -> bool:
    return (root / ".git").is_dir()


def _git_head(root: Path) -> Optional[str]:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if r.returncode == 0:
            return (r.stdout or "").strip() or None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def try_git_pull(root: Path, *, force: bool = False) -> Tuple[bool, str]:
    """``git pull --ff-only`` on *root* when it is a git checkout."""
    root = root.resolve()
    if not is_git_repo(root):
        return False, "not a git repo (skipping pull)"

    stamp = _pull_stamp_path(root)
    now = time.time()
    if not force and stamp.is_file():
        try:
            data = json.loads(stamp.read_text(encoding="utf-8"))
            last = float(data.get("ts") or 0)
            if now - last < _PULL_COOLDOWN_SEC:
                return False, "git pull skipped (cooldown)"
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass

    before = _git_head(root)
    try:
        fetch = subprocess.run(
            ["git", "-C", str(root), "fetch", "--quiet", "origin"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if fetch.returncode != 0:
            tail = (fetch.stderr or fetch.stdout or "").strip()[-200:]
            return False, f"git fetch failed: {tail or fetch.returncode}"

        pull = subprocess.run(
            ["git", "-C", str(root), "pull", "--ff-only", "--quiet"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except FileNotFoundError:
        return False, "git not on PATH — install Git for Windows or clone manually"
    except subprocess.TimeoutExpired:
        return False, "git pull timed out"

    if pull.returncode != 0:
        tail = (pull.stderr or pull.stdout or "").strip()[-200:]
        return False, f"git pull failed: {tail or pull.returncode}"

    after = _git_head(root)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(
        json.dumps({"ts": now, "path": str(root), "head": after}, indent=2) + "\n",
        encoding="utf-8",
    )
    if before and after and before != after:
        ver = plugin_version(root)
        return True, f"git pull updated to v{ver}" if ver else "git pull updated"
    return False, "git pull: already up to date"


def try_clone_standard_repo() -> Tuple[bool, str, Optional[Path]]:
    """Clone GitHub tree to ``~/.claude/plugins/ainl-cortex`` when missing."""
    standard = standard_plugin_path()
    if is_valid_plugin_root(standard):
        return True, f"live install already at {standard}", standard

    if standard.exists():
        return False, f"{standard} exists but is not a valid plugin tree", None

    standard.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", REPO_URL, str(standard)],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except FileNotFoundError:
        return False, "git not on PATH — run setup.cmd from a downloaded zip", None
    except subprocess.TimeoutExpired:
        return False, "git clone timed out", None

    if proc.returncode != 0:
        tail = ((proc.stderr or "") + (proc.stdout or "")).strip()[-300:]
        return False, f"git clone failed: {tail}", None

    if not is_valid_plugin_root(standard):
        return False, f"clone at {standard} missing hooks/startup.py", None

    ver = plugin_version(standard)
    msg = f"cloned live install to {standard}"
    if ver:
        msg += f" (v{ver})"
    return True, msg, standard


def maybe_refresh_plugin_code(
    running_root: Optional[Path] = None,
) -> Tuple[bool, List[str], Path]:
    """
    Pull latest git source and prefer live install over marketplace cache.

    Returns (reload_recommended, action_messages, effective_root).
    """
    running_root = (running_root or Path.cwd()).resolve()
    actions: List[str] = []
    reload = False

    standard = standard_plugin_path()
    canonical = canonical_plugin_root(running_root)

    if is_cache_plugin_path(running_root):
        actions.append(
            f"Claude loaded marketplace cache ({running_root.name}); "
            "preferring live git install for updates"
        )

    target = canonical
    if is_cache_plugin_path(running_root) and is_valid_plugin_root(standard):
        target = standard.resolve()
    elif is_cache_plugin_path(running_root) and not is_valid_plugin_root(standard):
        ok, msg, cloned = try_clone_standard_repo()
        actions.append(msg)
        if ok and cloned is not None:
            target = cloned.resolve()
            reload = True
        else:
            return reload, actions, running_root

    if is_git_repo(target):
        updated, msg = try_git_pull(target)
        actions.append(msg)
        if updated:
            reload = True
            try:
                from .build_stamp import write_install_stamp

                write_install_stamp(target)
            except Exception:
                pass
    elif is_cache_plugin_path(running_root):
        actions.append(
            "no git tree for auto-update — clone to "
            f"{standard} or run setup.cmd after git pull"
        )

    if target != running_root:
        actions.append(f"effective plugin root → {target}")

    return reload, actions, target
