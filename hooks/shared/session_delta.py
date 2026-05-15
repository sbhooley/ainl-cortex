"""
Session delta: tamper-evident audit log of memory changes per session.

Each session gets a UUID written to inbox at startup. At session end,
stop.py collects every node written, hashes its content, and appends one
record to logs/session_deltas.jsonl.

The log is append-only. Each record answers:
  - What changed (node IDs + types)
  - What the content was at write time (SHA-256 prefix of data JSON)
  - Which session and project wrote it
  - When it was written

This is not a cryptographic proof of authenticity — a local adversary with
filesystem access can modify both the DB and the log. It IS a practical audit
trail for accidental corruption and cross-session diffs.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List


# ── Session ID lifecycle ──────────────────────────────────────────────────────

def _sid_path(project_id: str, plugin_root: Path) -> Path:
    return plugin_root / "inbox" / f"{project_id}_session_id.txt"


def write_session_id(project_id: str, plugin_root: Path) -> str:
    """Generate a fresh session UUID, persist it, and return it.
    Called once by the startup hook at session start."""
    sid = str(uuid.uuid4())
    path = _sid_path(project_id, plugin_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sid)
    return sid


def read_session_id(project_id: str, plugin_root: Path) -> str:
    """Read the session UUID written by startup. Returns a fallback UUID
    when startup did not run (e.g. mid-session reload)."""
    path = _sid_path(project_id, plugin_root)
    if path.exists():
        try:
            return path.read_text().strip()
        except OSError:
            pass
    return str(uuid.uuid4())


def session_started_at(project_id: str, plugin_root: Path) -> float:
    """Return the mtime of the session ID file as the session start timestamp."""
    path = _sid_path(project_id, plugin_root)
    try:
        return path.stat().st_mtime
    except OSError:
        return time.time()


# ── Node content hashing ──────────────────────────────────────────────────────

def node_content_hash(node) -> str:
    """SHA-256 of the node's data dict (first 16 hex chars).
    Stable across Python versions; sort_keys ensures determinism."""
    content = json.dumps(node.data, sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# ── Store write interceptor ───────────────────────────────────────────────────

def wrap_store_for_delta(store, delta_entries: List[Dict[str, Any]]):
    """Monkey-patch store.write_node to capture every write into delta_entries.
    Returns the same store object (mutated in place)."""
    original_write = store.write_node

    def _capturing_write(node):
        delta_entries.append({
            "node_id": node.id,
            "node_type": node.node_type.value if hasattr(node.node_type, "value") else str(node.node_type),
            "content_hash": node_content_hash(node),
        })
        return original_write(node)

    store.write_node = _capturing_write
    return store


# ── Compaction recovery ───────────────────────────────────────────────────────

def build_compaction_brief(
    plugin_root: Path,
    max_sessions: int = 3,
    max_age_days: int = 30,
) -> str:
    """Build a recovery brief from the last N session delta records.

    Returned string is injected into the startup systemMessage for Python backend
    users so that context compaction does not erase awareness of recent writes.
    Returns empty string when no recent deltas exist.
    """
    delta_file = plugin_root / "logs" / "session_deltas.jsonl"
    if not delta_file.exists():
        return ""

    cutoff = time.time() - max_age_days * 86400
    try:
        raw_lines = delta_file.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return ""

    records: List[Dict[str, Any]] = []
    for line in reversed(raw_lines):
        try:
            r = json.loads(line)
            if r.get("finalized_at", 0) >= cutoff:
                records.append(r)
            if len(records) >= max_sessions:
                break
        except Exception:
            pass

    if not records:
        return ""

    out = ["**Prior Session Writes (compaction recovery):**"]
    for r in records:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(r.get("finalized_at", 0)))
        node_count = r.get("node_count", 0)
        type_tally: Dict[str, int] = {}
        for n in r.get("nodes", []):
            t = n.get("node_type", "?")
            type_tally[t] = type_tally.get(t, 0) + 1
        type_summary = ", ".join(
            f"{v}×{k}" for k, v in sorted(type_tally.items())
        )
        out.append(
            f"- [{ts}] session {r.get('session_id', '?')[:8]}… "
            f"→ {node_count} nodes ({type_summary or 'none'})"
        )

    return "\n".join(out)


# ── Delta file writer ─────────────────────────────────────────────────────────

def append_session_delta(
    plugin_root: Path,
    session_id: str,
    project_id: str,
    started_at: float,
    nodes: List[Dict[str, Any]],
) -> None:
    """Append one session record to logs/session_deltas.jsonl (append-only)."""
    if not nodes:
        return
    delta_dir = plugin_root / "logs"
    delta_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "session_id": session_id,
        "project_id": project_id,
        "started_at": round(started_at, 3),
        "finalized_at": round(time.time(), 3),
        "node_count": len(nodes),
        "nodes": nodes,
    }
    with open(delta_dir / "session_deltas.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
