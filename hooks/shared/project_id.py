"""
Project ID Detection

Single stable ID scoped to this Claude Code installation (~/.claude).
The plugin is a user-level tool, not a per-repo tool — all sessions
on this machine share one memory bucket regardless of working directory.
"""

import hashlib
import subprocess
from pathlib import Path
from typing import Optional

# Stable anchor: the user's Claude config directory.
# Same on every session regardless of which repo is open.
_CLAUDE_DIR = Path.home() / ".claude"
GLOBAL_PROJECT_ID = hashlib.sha256(str(_CLAUDE_DIR.resolve()).encode()).hexdigest()[:16]


def get_project_id(cwd: Optional[Path] = None) -> str:
    """
    Return the single stable project ID for this Claude Code installation.

    cwd is accepted for API compatibility but ignored — the plugin uses
    a global ID so memory accumulates across all projects uniformly.
    """
    return GLOBAL_PROJECT_ID


def get_project_info(cwd: Optional[Path] = None) -> dict:
    """
    Get extended project information.

    Returns dict with project_id, path, git info, etc.
    """
    if cwd is None:
        cwd = Path.cwd()

    info = {
        "project_id": GLOBAL_PROJECT_ID,
        "path": str(cwd.resolve()),
    }

    return info
