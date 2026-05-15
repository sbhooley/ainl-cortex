"""
Project ID resolution.

Each Claude Code working directory should map to ONE memory bucket. The default
("per_repo") anchors the bucket on the git toplevel of `cwd` so two clones of
the same project share state, while two unrelated repos do not.

Behavior matrix
---------------

  memory.project_isolation_mode (config.json) | resolver
  --------------------------------------------|---------------------------------
  per_repo (default)                          | git toplevel hash, else cwd hash
  global (back-compat escape hatch)           | sha256("~/.claude")[:16] (LEGACY)

The legacy global ID is preserved as `LEGACY_GLOBAL_PROJECT_ID` so:
  * the read-fallback chain (`get_project_id_chain`) can also surface
    pre-rewrite memories without losing data, and
  * `scripts/repartition_by_repo.py` knows which legacy bucket to drain.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Optional

# ── Legacy bucket ────────────────────────────────────────────────────────────
_CLAUDE_DIR = Path.home() / ".claude"
LEGACY_GLOBAL_PROJECT_ID = hashlib.sha256(
    str(_CLAUDE_DIR.resolve()).encode()
).hexdigest()[:16]
# Back-compat alias — old call sites that imported GLOBAL_PROJECT_ID still work.
GLOBAL_PROJECT_ID = LEGACY_GLOBAL_PROJECT_ID

# ── Config ───────────────────────────────────────────────────────────────────
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = _PLUGIN_ROOT / "config.json"

_VALID_MODES = ("per_repo", "global")


def _isolation_mode() -> str:
    """Read `memory.project_isolation_mode` from config.json with env override.

    Returns 'per_repo' (default) or 'global'.
    """
    env = os.environ.get("AINL_CORTEX_PROJECT_ISOLATION_MODE", "").strip().lower()
    if env in _VALID_MODES:
        return env
    try:
        cfg = json.loads(_CONFIG_PATH.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        cfg = {}
    raw = (cfg.get("memory", {}) or {}).get("project_isolation_mode", "per_repo")
    return raw if raw in _VALID_MODES else "per_repo"


# ── Resolver helpers ─────────────────────────────────────────────────────────

def _hash_anchor(anchor: Path) -> str:
    """Stable 16-char SHA-256 prefix of a filesystem path."""
    return hashlib.sha256(str(anchor.resolve()).encode()).hexdigest()[:16]


def get_git_branch(cwd: Optional[Path] = None) -> Optional[str]:
    """Return the current git branch name, or None if not in a repo / detached HEAD."""
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd or Path.cwd()), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=2.0, check=False,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            return branch if branch and branch != "HEAD" else None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _git_toplevel(cwd: Path) -> Optional[Path]:
    """Return the git repo toplevel for `cwd`, or None if not a git repo / git missing.

    Bounded to a 2s timeout so a stuck git process never blocks a hook.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    if not out:
        return None
    return Path(out)


@lru_cache(maxsize=64)
def _resolve_project_id(cwd_str: str, mode: str) -> str:
    """Cached per-cwd resolver. `mode` is part of the key so a config change
    that flips isolation mode mid-process produces fresh results."""
    if mode == "global":
        return LEGACY_GLOBAL_PROJECT_ID
    cwd = Path(cwd_str)
    top = _git_toplevel(cwd)
    if top is not None:
        return _hash_anchor(top)
    # Fallback for non-git cwds: anchor on cwd itself.
    return _hash_anchor(cwd)


def get_project_id(cwd: Optional[Path] = None) -> str:
    """Return the project ID for `cwd` under the active isolation mode.

    `cwd` defaults to `Path.cwd()`. Hooks should always pass the cwd from the
    Claude Code event payload (the process cwd is usually the plugin root, not
    the user's repo)."""
    if cwd is None:
        cwd = Path.cwd()
    return _resolve_project_id(str(cwd), _isolation_mode())


def get_project_id_chain(cwd: Optional[Path] = None) -> List[str]:
    """Return the read-fallback chain: [per_repo_id, LEGACY_GLOBAL_PROJECT_ID].

    The first element is the active per-repo (or global) ID; the second is
    always the legacy global bucket so reads still surface pre-issue-1
    memories until `scripts/repartition_by_repo.py` runs. Duplicates removed
    while preserving order."""
    primary = get_project_id(cwd)
    chain: List[str] = [primary]
    if LEGACY_GLOBAL_PROJECT_ID != primary:
        chain.append(LEGACY_GLOBAL_PROJECT_ID)
    return chain


def get_project_info(cwd: Optional[Path] = None) -> dict:
    """Return extended project information including the resolver decision.

    The `git_toplevel` field is None for non-git cwds. `isolation_mode` reflects
    the effective config value, after env-var override."""
    if cwd is None:
        cwd = Path.cwd()
    mode = _isolation_mode()
    top = _git_toplevel(cwd) if mode == "per_repo" else None
    return {
        "project_id": get_project_id(cwd),
        "project_id_chain": get_project_id_chain(cwd),
        "isolation_mode": mode,
        "path": str(cwd.resolve()),
        "git_toplevel": str(top) if top else None,
        "legacy_global_project_id": LEGACY_GLOBAL_PROJECT_ID,
    }


def reset_cache() -> None:
    """Clear the in-process resolver cache. Used by tests."""
    _resolve_project_id.cache_clear()


# ── Module-level helper for callers that do their own iteration ──────────────

def iter_project_ids(cwd: Optional[Path] = None) -> Iterable[str]:
    """Yield each project_id in the legacy chain, in priority order."""
    yield from get_project_id_chain(cwd)
