"""SessionStart operator visibility (Claude Code 2.1.139+).

SessionStart hooks inject context for Claude but often do not show ``systemMessage``
or stderr in the UI. MCP can be connected while the operator sees no banner.

This module:
- Persists a one-line summary for the first ``UserPromptSubmit`` (shown in transcript).
- Builds ``terminalSequence`` for desktop notifications (OSC 9 / 777).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, Optional


def first_banner_line(system_message: str) -> str:
    for line in (system_message or "").splitlines():
        if line.strip():
            return line.strip()
    return "[AINL Cortex] active"


def build_sessionstart_terminal_sequence(one_line: str) -> str:
    """OSC sequences Claude Code may emit (v2.1.141+). Empty when disabled."""
    if os.environ.get("AINL_CORTEX_SESSIONSTART_NOTIFY", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return ""
    title = "AINL Cortex"
    body = (one_line or title).replace("\n", " ").replace("\007", "")[:200]
    parts = [
        f"\033]9;{title};{body}\007",
        f"\033]777;notify;{title};{body}\007",
        f"\033]0;{title}: ready\007",
    ]
    return "".join(parts)


def _pending_path(root: Path) -> Path:
    return root / "logs" / "session_banner_transcript.json"


def write_transcript_pending(
    root: Path,
    session_id: str,
    one_line: str,
    *,
    source: str = "startup",
) -> None:
    if not (session_id or "").strip():
        return
    try:
        log_dir = root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": session_id.strip(),
            "one_line": (one_line or "").strip() or "[AINL Cortex] active",
            "source": source,
            "ts": time.time(),
        }
        _pending_path(root).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def consume_transcript_pending(root: Path, session_id: str) -> Optional[str]:
    """Return one-line banner for this session once, then clear."""
    sid = (session_id or "").strip()
    if not sid:
        return None
    path = _pending_path(root)
    try:
        if not path.is_file():
            return None
        data: Mapping[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if data.get("session_id") != sid:
            return None
        line = str(data.get("one_line") or "").strip()
        path.unlink(missing_ok=True)
        return line or None
    except (OSError, json.JSONDecodeError, TypeError):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
