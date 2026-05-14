"""
Local Claude Code instance registry and mailbox.

Each Claude Code instance with ainl-cortex registers itself at SessionStart
under a name (AINL_AGENT_NAME env var, or auto-derived from git repo basename).
Other instances discover it by reading the shared registry directory and can
deliver messages to its file-based mailbox.

  Registry: <plugin_root>/registry/<name>.json
  Mailbox:  <plugin_root>/mailboxes/<name>/<uuid>.json

Everything is plain file I/O — no sockets, no daemon. Works across terminals
on the same machine because all Claude Code instances share the same plugin
installation directory (~/.claude/plugins/ainl-cortex/).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

_ENV_VAR = "AINL_AGENT_NAME"
_URGENCY_ORDER = {"critical": 0, "normal": 1, "low": 2}


# ── Name resolution ────────────────────────────────────────────────────────

def _git_repo_slug(cwd: Optional[Path] = None) -> Optional[str]:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd or Path.cwd()),
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0:
            return Path(r.stdout.strip()).name
    except Exception:
        pass
    return None


def _sanitise(name: str) -> str:
    return ("".join(c if c.isalnum() or c == "-" else "-" for c in name.lower())
            .strip("-") or "claude-default")


def get_agent_name(cwd: Optional[Path] = None) -> str:
    """
    Resolve the local agent name for this Claude Code instance.

    Priority:
    1. AINL_AGENT_NAME env var  — explicit; recommended when running multiple
       terminals in the same project (set different names per terminal)
    2. claude-{git-repo-name}   — auto-derived; one stable name per project
    3. claude-default            — fallback outside any git repo
    """
    env = os.environ.get(_ENV_VAR, "").strip()
    if env:
        return _sanitise(env)
    slug = _git_repo_slug(cwd)
    if slug:
        return f"claude-{_sanitise(slug)}"
    return "claude-default"


# ── Registry ───────────────────────────────────────────────────────────────

def _registry_file(plugin_root: Path, name: str) -> Path:
    return plugin_root / "registry" / f"{name}.json"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except Exception:
        return False


def register_self(plugin_root: Path, name: str, cwd: Optional[Path] = None) -> None:
    """Write this instance's registry entry. Idempotent — safe on every SessionStart."""
    _atomic_write(_registry_file(plugin_root, name), {
        "name": name,
        "pid": os.getpid(),
        "project": str(cwd or Path.cwd()),
        "registered_at": int(time.time()),
        "type": "claude-code",
    })


def deregister_self(plugin_root: Path, name: str) -> None:
    """Remove this instance's registry entry on clean shutdown."""
    try:
        _registry_file(plugin_root, name).unlink(missing_ok=True)
    except Exception:
        pass


def list_live_agents(plugin_root: Path, cleanup_stale: bool = True) -> List[Dict[str, Any]]:
    """
    Return all live local Claude Code instances.

    Checks each registered PID with os.kill(pid, 0). Stale entries (dead PID)
    are removed when cleanup_stale=True.
    """
    reg_dir = plugin_root / "registry"
    if not reg_dir.exists():
        return []
    agents = []
    for f in reg_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        if _is_pid_alive(data.get("pid", 0)):
            agents.append(data)
        elif cleanup_stale:
            f.unlink(missing_ok=True)
    return agents


def is_local_agent(plugin_root: Path, name: str) -> bool:
    """True if a live Claude Code instance with this name is registered."""
    f = _registry_file(plugin_root, name)
    if not f.exists():
        return False
    try:
        return _is_pid_alive(json.loads(f.read_text()).get("pid", 0))
    except Exception:
        return False


# ── Mailbox ────────────────────────────────────────────────────────────────

def _mailbox_dir(plugin_root: Path, name: str) -> Path:
    return plugin_root / "mailboxes" / name


def write_message(
    plugin_root: Path,
    to: str,
    message: str,
    from_agent: str,
    urgency: str = "normal",
    thread_id: Optional[str] = None,
) -> str:
    """Write a message to the target agent's mailbox. Returns the message ID."""
    msg_id = str(uuid.uuid4())
    mbox = _mailbox_dir(plugin_root, to)
    mbox.mkdir(parents=True, exist_ok=True)
    _atomic_write(mbox / f"{msg_id}.json", {
        "id": msg_id,
        "from": from_agent,
        "to": to,
        "message": message,
        "urgency": urgency,
        "thread_id": thread_id or str(uuid.uuid4()),
        "created_at": int(time.time()),
        "type": "local",
    })
    return msg_id


def drain_mailbox(
    plugin_root: Path,
    name: str,
    max_messages: int = 50,
    max_age_seconds: int = 86400,
) -> List[Dict[str, Any]]:
    """
    Read and delete all pending messages from this agent's mailbox.

    Returns messages sorted by urgency (critical first) then recency.
    Expired messages are silently dropped.
    """
    mbox = _mailbox_dir(plugin_root, name)
    if not mbox.exists():
        return []

    cutoff = int(time.time()) - max_age_seconds
    pending = []
    for f in mbox.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if data.get("created_at", 0) < cutoff:
                f.unlink(missing_ok=True)
                continue
            pending.append((data, f))
        except Exception:
            continue

    pending.sort(key=lambda x: (
        _URGENCY_ORDER.get(x[0].get("urgency", "normal"), 1),
        -x[0].get("created_at", 0),
    ))

    result = []
    for data, f in pending[:max_messages]:
        result.append(data)
        f.unlink(missing_ok=True)
    return result


def peek_mailbox(plugin_root: Path, name: str) -> int:
    """Count pending messages without consuming them."""
    mbox = _mailbox_dir(plugin_root, name)
    if not mbox.exists():
        return 0
    return sum(1 for _ in mbox.glob("*.json"))
