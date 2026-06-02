"""Heuristic tool-result digests (zero-LLM) for graph-backed recall."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple

DEFAULT_THRESHOLD_CHARS = 4000
DEFAULT_DIGEST_MAX_CHARS = 1200

_DIGEST_TOOLS = frozenset(
    {
        "read",
        "grep",
        "bash",
        "shell",
        "write",
        "edit",
        "mcp",
        "web_fetch",
        "web_search",
    }
)


def _effective_threshold(tool_name: str, threshold_chars: int) -> int:
    canon = (tool_name or "").lower().replace(" ", "_")
    if canon in ("web_search", "web_fetch"):
        try:
            try:
                from .knowledge_config import research_cfg
            except ImportError:
                from knowledge_config import research_cfg

            return int(research_cfg().get("web_digest_threshold_chars", 800))
        except Exception:
            return 800
    return threshold_chars


def should_digest(tool_name: str, result_text: str, threshold_chars: int = DEFAULT_THRESHOLD_CHARS) -> bool:
    threshold_chars = _effective_threshold(tool_name, threshold_chars)
    if not result_text or len(result_text) < threshold_chars:
        return False
    canon = (tool_name or "").lower().replace(" ", "_")
    if any(canon.startswith(p) for p in _DIGEST_TOOLS):
        return True
    return len(result_text) >= threshold_chars * 2


def build_digest(tool_name: str, result_text: str, max_chars: int = DEFAULT_DIGEST_MAX_CHARS) -> str:
    """Build a compact digest; full payload stored separately."""
    lines = result_text.splitlines()
    head = lines[:8]
    tail = lines[-5:] if len(lines) > 13 else []
    err_lines = [ln for ln in lines if re.search(r"\b(error|failed|exception|traceback)\b", ln, re.I)][:5]
    paths = re.findall(
        r'\b[\w./\\-]+\.(?:py|ts|tsx|js|json|yaml|yml|md|ainl|rs|toml)\b',
        result_text[:8000],
    )[:12]

    parts = [f"tool={tool_name}", f"chars={len(result_text)}"]
    if paths:
        parts.append("paths=" + ", ".join(dict.fromkeys(paths)[:8]))
    if err_lines:
        parts.append("errors:\n" + "\n".join(err_lines[:3]))
    body = "\n".join(head)
    if tail and tail != head:
        body += "\n...\n" + "\n".join(tail)
    out = " | ".join(parts) + "\n" + body
    if len(out) > max_chars:
        out = out[: max_chars - 40] + "\n[... digest truncated]"
    return out


def store_tool_outcome_blob(
    plugin_root,
    project_id: str,
    blob_id: str,
    full_text: str,
) -> str:
    """Write full tool output under graph_memory/tool_blobs (gitignored via user home)."""
    from pathlib import Path

    base = Path.home() / ".claude" / "projects" / project_id / "graph_memory" / "tool_blobs"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{blob_id}.txt"
    path.write_text(full_text, encoding="utf-8")
    return str(path)


def load_tool_outcome_blob(project_id: str, blob_id: str) -> Optional[str]:
    from pathlib import Path

    path = Path.home() / ".claude" / "projects" / project_id / "graph_memory" / "tool_blobs" / f"{blob_id}.txt"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
