"""
Read the latest assistant (and optional user) text from Claude Code session JSONL.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, List, Optional, Sequence

logger = logging.getLogger(__name__)

_TEXT_BLOCK_TYPES = frozenset({"text", "output_text"})


def _text_from_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: List[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        btype = (block.get("type") or "").lower()
        if btype in _TEXT_BLOCK_TYPES:
            text = block.get("text") or block.get("content") or ""
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        elif btype == "tool_result":
            inner = block.get("content")
            if isinstance(inner, str) and inner.strip():
                parts.append(inner.strip()[:2000])
    return "\n\n".join(parts).strip()


def _iter_transcript_records(path: Path, *, tail_bytes: int = 2_000_000):
    """Yield parsed JSON objects from the end of a transcript file (newest last)."""
    try:
        size = path.stat().st_size
    except OSError:
        return
    start = max(0, size - tail_bytes)
    try:
        with open(path, "rb") as f:
            if start:
                f.seek(start)
                f.readline()  # drop partial line
            raw = f.read().decode("utf-8", errors="replace")
    except OSError as e:
        logger.debug("transcript read failed: %s", e)
        return

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            yield rec


def _message_text(rec: dict) -> str:
    msg = rec.get("message")
    if isinstance(msg, dict):
        return _text_from_content(msg.get("content"))
    return _text_from_content(rec.get("content"))


def _open_transcript_path(transcript_path: str | Path) -> Path:
    try:
        from .claude_paths import normalize_transcript_path
    except ImportError:
        from claude_paths import normalize_transcript_path
    return normalize_transcript_path(transcript_path)


def read_last_assistant_text(
    transcript_path: str | Path,
    *,
    max_chars: int = 12_000,
    min_chars: int = 80,
    tail_bytes: int = 2_000_000,
) -> str:
    """Return the most recent non-empty assistant message text."""
    path = _open_transcript_path(transcript_path)
    if not path.is_file():
        return ""

    last = ""
    for rec in _iter_transcript_records(path, tail_bytes=tail_bytes):
        if rec.get("isMeta"):
            continue
        if (rec.get("type") or "").lower() != "assistant":
            continue
        text = _message_text(rec)
        if len(text) >= min_chars:
            last = text

    if not last:
        return ""
    if len(last) > max_chars:
        return last[-max_chars:]
    return last


def read_recent_assistant_chunks(
    transcript_path: str | Path,
    *,
    max_messages: int = 3,
    max_chars: int = 16_000,
    min_chars: int = 40,
) -> str:
    """Concatenate up to N recent assistant messages (oldest first within cap)."""
    path = _open_transcript_path(transcript_path)
    if not path.is_file():
        return ""

    chunks: List[str] = []
    for rec in _iter_transcript_records(path):
        if rec.get("isMeta"):
            continue
        if (rec.get("type") or "").lower() != "assistant":
            continue
        text = _message_text(rec)
        if len(text) < min_chars:
            continue
        chunks.append(text)
        if len(chunks) > max_messages:
            chunks.pop(0)

    if not chunks:
        return ""
    combined = "\n\n---\n\n".join(chunks)
    if len(combined) > max_chars:
        return combined[-max_chars:]
    return combined


def strip_remember_command_prefix(prompt: str) -> str:
    """Remove short imperative prefixes so pasted body can be ingested."""
    if not prompt:
        return ""
    lines = prompt.strip().splitlines()
    if not lines:
        return ""

    lower_first = lines[0].lower().strip()
    prefixes = (
        "remember this",
        "remember that",
        "save this to memory",
        "save that to memory",
        "save to graph memory",
        "save to memory",
        "store this in memory",
        "store in graph memory",
        "commit this to memory",
        "commit to graph memory",
        "commit to memory",
        "ingest this",
        "ingest that",
        "keep this in your memory",
        "put this in memory",
        "add this to memory",
    )
    for p in prefixes:
        if lower_first == p or lower_first.startswith(p + ":") or lower_first.startswith(p + " "):
            rest = lines[0][len(p) :].lstrip(" :,-")
            if rest:
                lines[0] = rest
            else:
                lines = lines[1:]
            break

    return "\n".join(lines).strip()
