"""
Accumulate tool captures across UserPromptSubmit flushes.

Per-prompt flush merges drained captures into a pending session file and only
persists failures (durability). Stop drains any remaining captures, merges with
pending, and runs a single finalize_session (one native episode per chat session).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


def _pending_path(inbox_dir: Path, project_id: str) -> Path:
    return inbox_dir / f"{project_id}_session_pending.json"


def empty_session() -> Dict[str, Any]:
    return {
        "tool_captures": [],
        "files_touched": [],
        "tools_used": [],
        "had_errors": False,
        "turn_id": None,
        "session_id": None,
    }


def merge_session_batches(
    base: Optional[Dict[str, Any]],
    batch: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge two session_data dicts (from drain_session_inbox shape)."""
    if not base:
        base = empty_session()
    if not batch:
        return dict(base)

    files = set(base.get("files_touched") or [])
    files.update(batch.get("files_touched") or [])
    tools = set(base.get("tools_used") or [])
    tools.update(batch.get("tools_used") or [])

    merged = {
        "tool_captures": list(base.get("tool_captures") or [])
        + list(batch.get("tool_captures") or []),
        "files_touched": sorted(files),
        "tools_used": sorted(tools),
        "had_errors": bool(base.get("had_errors")) or bool(batch.get("had_errors")),
        "turn_id": base.get("turn_id") or batch.get("turn_id"),
        "session_id": base.get("session_id") or batch.get("session_id"),
    }
    return merged


def load_pending_session(inbox_dir: Path, project_id: str) -> Dict[str, Any]:
    path = _pending_path(inbox_dir, project_id)
    if not path.exists():
        return empty_session()
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return empty_session()
        out = empty_session()
        out.update(data)
        return out
    except (OSError, json.JSONDecodeError, ValueError):
        return empty_session()


def save_pending_session(
    inbox_dir: Path, project_id: str, session_data: Dict[str, Any]
) -> None:
    path = _pending_path(inbox_dir, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(session_data, default=str))
    tmp.replace(path)


def clear_pending_session(inbox_dir: Path, project_id: str) -> None:
    path = _pending_path(inbox_dir, project_id)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def ensure_session_identity(
    session_data: Dict[str, Any],
    *,
    plugin_root: Optional[Path] = None,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Assign stable turn_id / Claude session_id for the pending window."""
    if not session_data.get("turn_id"):
        session_data["turn_id"] = str(uuid.uuid4())
    if not session_data.get("session_id") and plugin_root and project_id:
        try:
            from shared.session_delta import read_session_id

            session_data["session_id"] = read_session_id(project_id, plugin_root)
        except Exception:
            pass
    return session_data


def accumulate_into_pending(
    inbox_dir: Path,
    project_id: str,
    batch: Dict[str, Any],
    *,
    plugin_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Merge a drained capture batch into the pending session file."""
    pending = load_pending_session(inbox_dir, project_id)
    merged = merge_session_batches(pending, batch)
    ensure_session_identity(
        merged, plugin_root=plugin_root, project_id=project_id
    )
    save_pending_session(inbox_dir, project_id, merged)
    return merged


def collect_session_for_finalize(
    inbox_dir: Path,
    project_id: str,
    batch: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge pending + latest drained batch; clear pending on success path."""
    pending = load_pending_session(inbox_dir, project_id)
    merged = merge_session_batches(pending, batch)
    clear_pending_session(inbox_dir, project_id)
    return merged
