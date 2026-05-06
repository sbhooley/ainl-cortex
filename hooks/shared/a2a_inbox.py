"""
A2A inbox read/write utilities.

Inbox uses individual JSON files per message for atomic writes.
Self-inbox is a separate directory for cross-session Claude self-notes.
"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import List, Dict, Any


URGENCY_ORDER = {"critical": 0, "normal": 1, "low": 2}


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def read_inbox(
    inbox_dir: Path,
    max_messages: int = 50,
    max_age_seconds: int = 86400,
    max_message_chars: int = 2000,
) -> List[Dict[str, Any]]:
    """Read and return inbox messages sorted by urgency then recency."""
    messages = []
    now = int(time.time())
    cutoff = now - max_age_seconds

    if not inbox_dir.exists():
        return []

    for f in inbox_dir.glob("*.json"):
        try:
            msg = json.loads(f.read_text())
            if msg.get("received_at", 0) < cutoff:
                f.unlink(missing_ok=True)
                continue
            # Truncate message for injection
            text = msg.get("message", "")
            if len(text) > max_message_chars:
                msg["message"] = text[:max_message_chars] + "...[truncated]"
                msg["truncated"] = True
            messages.append(msg)
        except Exception:
            continue

    messages.sort(
        key=lambda m: (
            URGENCY_ORDER.get(m.get("urgency", "normal"), 1),
            -(m.get("received_at", 0)),
        )
    )

    # critical always included; cap normal+low together
    critical = [m for m in messages if m.get("urgency") == "critical"]
    rest = [m for m in messages if m.get("urgency") != "critical"]
    cap = max(0, max_messages - len(critical))
    return critical + rest[:cap]


def clear_inbox(inbox_dir: Path) -> None:
    if not inbox_dir.exists():
        return
    for f in inbox_dir.glob("*.json"):
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass


def write_message(inbox_dir: Path, msg: dict) -> str:
    """Write a message dict to inbox. Returns the message id."""
    inbox_dir.mkdir(parents=True, exist_ok=True)
    msg_id = msg.get("id") or str(uuid.uuid4())
    msg["id"] = msg_id
    _atomic_write(inbox_dir / f"{msg_id}.json", msg)
    return msg_id


def write_self_note(
    plugin_root: Path,
    message: str,
    context: str = "",
    urgency: str = "critical",
    tool_count: int = 0,
) -> str:
    """Write a self-note to the self_inbox for pickup at next SessionStart."""
    self_inbox = plugin_root / "a2a" / "self_inbox"
    self_inbox.mkdir(parents=True, exist_ok=True)
    note_id = str(uuid.uuid4())
    note = {
        "id": note_id,
        "type": "self_note",
        "message": message,
        "context": context,
        "urgency": urgency,
        "created_at": int(time.time()),
        "session_tool_count": tool_count,
    }
    _atomic_write(self_inbox / f"{note_id}.json", note)
    return note_id


def read_self_inbox(plugin_root: Path) -> List[Dict[str, Any]]:
    """Read all self-notes, sorted newest first."""
    self_inbox = plugin_root / "a2a" / "self_inbox"
    if not self_inbox.exists():
        return []
    notes = []
    for f in self_inbox.glob("*.json"):
        try:
            notes.append(json.loads(f.read_text()))
        except Exception:
            continue
    notes.sort(key=lambda n: -n.get("created_at", 0))
    return notes


def clear_self_inbox(plugin_root: Path) -> None:
    self_inbox = plugin_root / "a2a" / "self_inbox"
    if not self_inbox.exists():
        return
    for f in self_inbox.glob("*.json"):
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass
